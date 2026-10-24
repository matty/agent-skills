"""Fixture regression test for the vrchat-world-qa skill's qa_measure.py.

Builds KIT, ASM and MASTER .blend files, FBX exports and PNGs with planted defects in a temp folder, runs qa_measure
on each in a fresh headless Blender, and checks that every defect is reported and the clean parts are not.

Host: Blender 5.2.2 (bpy), headless:
    blender -b --factory-startup --python-exit-code 1 --python tools/tests/blender/test_qa_measure_fixtures.py
Prints PASS <case> / FAIL <case>: <why> for each case and raises if any failed. Writes only to a temp folder.
"""

import json
import math
import shutil
import subprocess
import tempfile
import time
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[3]
QA = ROOT / "skills" / "vrchat-world-qa" / "scripts" / "qa_measure.py"
BLENDER = bpy.app.binary_path
BOX_FACES = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
# Run inside the open file: visibility states, measure(), the states again (qa_measure's path goes in at %r)
STATES_EXPR = """import bpy, json
def states():
    vl = bpy.context.view_layer
    seen = set(vl.objects)
    return {"excluded": sorted(lc.collection.name for lc in vl.layer_collection.children if lc.exclude),
            "coll_off": sorted(c.name for c in bpy.data.collections if c.hide_viewport),
            "obj_off": sorted(o.name for o in bpy.data.objects if o.hide_viewport),
            "eye": sorted(o.name for o in bpy.data.objects if o in seen and o.hide_get())}
before = states()
ns = {}
exec(compile(open(%r, encoding="utf-8").read(), "qa_measure.py", "exec"), ns)
rep = ns["measure"](module=1.0)
print("QA_STATES " + json.dumps({"before": before, "after": states(),
                                 "tris": {p["piece"]: p["lod0_tris"] for p in rep["pieces"]}}))
"""


# ---- fixture building -------------------------------------------------------------------------------------------

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.filepaths.save_version = 0


def save(path):
    bpy.ops.wm.save_as_mainfile(filepath=str(path))


def box_verts(lo, hi):
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    return [(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]


def mesh(name, verts, edges=(), faces=()):
    me = bpy.data.meshes.new(name)
    me.from_pydata(list(verts), list(edges), list(faces))
    me.update()
    return me


def box(name, lo, hi):
    return mesh(name, box_verts(lo, hi), (), BOX_FACES)


def piece(name, objects, status=None, parent=None):
    """A piece collection; objects: [(object name, mesh)]."""
    coll = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(coll)
    for obname, me in objects:
        coll.objects.link(bpy.data.objects.new(obname, me))
    if status:
        coll["kit_status"] = status
    return coll


def instance(name, coll, loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1), parent=None):
    ob = bpy.data.objects.new(name, None)
    ob.instance_type = "COLLECTION"
    ob.instance_collection = coll
    ob.location = loc
    ob.rotation_euler = [math.radians(r) for r in rot]
    ob.scale = scale
    (parent or bpy.context.scene.collection).objects.link(ob)
    return ob


def write_png(path, w, h, fill):
    """fill(x, y) -> (r, g, b) in 0-1, stored as 8-bit."""
    img = bpy.data.images.new(Path(path).stem, w, h, alpha=True)
    px = []
    for y in range(h):
        for x in range(w):
            px += list(fill(x, y)) + [1.0]
    img.pixels.foreach_set(px)
    img.filepath_raw = str(path)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def grid_uvs(me, m=0.05, lo=0.1, hi=0.9):
    """UVMap and UV2 with each face in its own grid cell (inner margin m): no overlaps, charts 2m apart, a bounding
    box of (hi - lo - 2m) squared."""
    n = len(me.polygons)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    w, h = (hi - lo) / cols, (hi - lo) / rows
    for name in ("UVMap", "UV2"):
        uvl = me.uv_layers.get(name) or me.uv_layers.new(name=name)
        for k, poly in enumerate(me.polygons):
            c, r = k % cols, k // cols
            corners = [(lo + c * w + m, lo + r * h + m), (lo + (c + 1) * w - m, lo + r * h + m),
                       (lo + (c + 1) * w - m, lo + (r + 1) * h - m), (lo + c * w + m, lo + (r + 1) * h - m)]
            for i, li in enumerate(poly.loop_indices):
                uvl.uv[li].vector = corners[i % 4]


def uv_by_vertex(me, fn):
    """UVMap and UV2 from each vertex (fn(index, co) -> (u, v)), so faces that share an edge share its UVs."""
    for name in ("UVMap", "UV2"):
        uvl = me.uv_layers.get(name) or me.uv_layers.new(name=name)
        for loop in me.loops:
            uvl.uv[loop.index].vector = fn(loop.vertex_index, me.vertices[loop.vertex_index].co)


def half_arch(name):
    """Half an arch band, from the apex (x 0) down to the floor and open there; UVMap and UV2 one strip chart, so a
    Mirror modifier at its defaults stacks the two halves' UV2 on each other."""
    verts = []
    for i in range(13):
        a = math.radians(90.0 * (1 - i / 12))
        verts += [(1.5 * math.cos(a), 0.0, 1.5 * math.sin(a)), (1.5 * math.cos(a), 0.3, 1.5 * math.sin(a))]
    me = mesh(name, verts, (), [(2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1) for i in range(12)])
    uv_by_vertex(me, lambda i, co: (0.3 + 0.2 * (i % 2), 0.1 + 0.8 * (i // 2) / 12.0))
    return me


def two_charts(name, a, b):
    """A 2 x 2 m plane of two quads sharing an edge, each its own UV2 chart: a and b are their u ranges."""
    me = mesh(name, [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 2, 0), (1, 2, 0), (2, 2, 0)], (), [(0, 1, 4, 3), (1, 2, 5, 4)])
    me.uv_layers.new(name="UVMap")
    uv2 = me.uv_layers.new(name="UV2")
    for poly, (u0, u1) in zip(me.polygons, (a, b)):
        for i, li in enumerate(poly.loop_indices):
            uv2.uv[li].vector = [(u0, 0.05), (u1, 0.05), (u1, 0.95), (u0, 0.95)][i]
    return me


def material(name, image=None):
    mat = bpy.data.materials.new(name)
    if image is not None:
        mat.node_tree.nodes.new("ShaderNodeTexImage").image = image
    return mat


def link(path, names, relative=True):
    with bpy.data.libraries.load(str(path), link=True, relative=relative) as (_src, dst):
        dst.collections = list(names)
    return {c.name: c for c in dst.collections}


def build(d):
    """Every fixture file; returns their paths."""
    f = {"kit": d / "KIT_Test.blend", "kit_abs": d / "KIT_Abs.blend", "asm": d / "ASM_Booth_A.blend",
         "master": d / "MASTER.blend", "fbx_dir": d / "fbx", "tex": d / "T_TST_Paint_BaseColor.png",
         "dark": d / "dark.png", "seamless": d / "seamless.png", "seamed": d / "seamed.png", "svg": d / "plan.svg",
         "kit_tex": d / "KIT_Tex.blend", "fbx_tex": d / "fbx_tex", "kit_half": d / "KIT_Half.blend",
         "asm_shift": d / "ASM_Shift_A.blend", "kit_lit": d / "KIT_Lit.blend", "kit_dense": d / "KIT_Dense.blend",
         "kit_hidden": d / "KIT_Hidden.blend", "rename": d / "rename", "kit_bakery": d / "KIT_Bakery.blend"}
    f["fbx_dir"].mkdir()

    reset()
    write_png(f["tex"], 64, 32, lambda x, y: (0.5, 0.4, 0.3))
    write_png(f["dark"], 32, 32, lambda x, y: (0.04, 0.04, 0.04))
    # a triangle wave tiles with every step equal (a sine would put the wrap on its steepest step: ratio ~1.6)
    write_png(f["seamless"], 64, 16, lambda x, y: (abs((x / 32.0) % 2.0 - 1.0),) * 3)
    write_png(f["seamed"], 64, 16, lambda x, y: (x / 63.0,) * 3)
    f["svg"].write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="220" viewBox="0 0 200 220" '
                        'data-px-per-m="10" data-origin="0,18" data-frame="20.0 20.0 160.0 180.0">'
                        '<rect width="100%" height="100%" fill="#fff"/></svg>\n', encoding="utf-8")

    # KIT_Test.blend: one clean piece and one planted defect per piece
    reset()
    paint = material("M_TST_Paint", bpy.data.images.load(str(f["tex"])))
    gone = bpy.data.images.new("T_TST_Gone", 8, 8)
    gone.source = "FILE"
    gone.filepath = str(d / "no_such_texture.png")
    wood = material("WoodFloor", gone)
    wall = box("wall", (0, 0, 0), (2, 0.2, 3))
    grid_uvs(wall)                                                  # six charts, bounding-box share 0.49
    wall.materials.append(paint)
    piece("TST_Wall_2x3_A", [("TST_Wall_2x3_A", wall)], "modelled")
    piece("TST_Wall_2x3", [("TST_Wall_2x3", box("bad", (0, 0, 0), (2, 0.2, 3)))], "modelled")       # no variant
    piece("TST_Panel_2x2_A", [("TST_Panel_2x2_A", mesh("panel", [(0, 0, 0), (2, 0, 0), (2, 0, 2), (1, 0, 2),
                                                                  (0, 0, 2)], (), [(0, 1, 2, 3, 4)]))], "grey")
    wire_v = box_verts((0, 0, 0), (1, 1, 1)) + [(0.2, 0.5, 0.5), (0.8, 0.5, 0.5)]
    piece("TST_Wire_1x1x1_A", [("TST_Wire_1x1x1_A", mesh("wire", wire_v, [(8, 9)], BOX_FACES))], "modelled")
    slab_v = box_verts((0, 0, 0), (2, 2, 0.1)) + [(0.5, 0.5, 0.1), (1.5, 0.5, 0.1), (1.5, 1.5, 0.1), (0.5, 1.5, 0.1)]
    piece("TST_Overlap_2x2_A", [("TST_Overlap_2x2_A", mesh("overlap", slab_v, (), BOX_FACES + [(8, 9, 10, 11)]))],
          "modelled")
    grid_v = [(x, y, 0) for y in (0, 1, 2) for x in (0, 1, 2)]
    grid = mesh("grid", grid_v, (), [(0, 1, 4, 3), (1, 2, 5, 4), (3, 4, 7, 6), (4, 5, 8, 7)])
    grid.materials.append(material("M_TST_Brick_Dark"))            # underscores in the name part are allowed
    grid.materials.append(material("M_TRIM_Sheet01"))              # a shared trim material on another family
    uvl = grid.uv_layers.new(name="UVMap")                          # planar, 4 m per tile: 256 px/m on a 1024 map
    for loop in grid.loops:
        co = grid.vertices[loop.vertex_index].co
        uvl.uv[loop.index].vector = (co.x / 4.0, co.y / 4.0)
    piece("TST_Grid_2x2_A", [("TST_Grid_2x2_A", grid)], "modelled")
    piece("TST_Gap_2x2_A", [("TST_Gap_2x2_A", two_charts("gap", (0.05, 0.45), (0.46, 0.95)))], "uv")
    piece("TST_Lap_2x2_A", [("TST_Lap_2x2_A", two_charts("lap", (0.05, 0.45), (0.40, 0.90)))], "uv")
    piece("TST_Good_2x2_A", [("TST_Good_2x2_A", two_charts("good", (0.05, 0.45), (0.55, 0.95)))], "uv")
    halves = d / "halves.png"                                       # left half black, right half white
    write_png(halves, 64, 64, lambda x, y: (1.0, 1.0, 1.0) if x >= 32 else (0.0, 0.0, 0.0))
    sw = mesh("uvswitch", [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)], (), [(0, 1, 2, 3)])
    sw0, sw2 = sw.uv_layers.new(name="UVMap"), sw.uv_layers.new(name="UV2")
    for i, (u, v) in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
        sw0.uv[i].vector, sw2.uv[i].vector = (u, v), (0.5 + 0.5 * u, v)    # UV2: the white half only
    half_mat = material("M_TST_Halves", bpy.data.images.load(str(halves)))
    half_mat.node_tree.nodes.active = next(n for n in half_mat.node_tree.nodes if n.type == "TEX_IMAGE")
    sw.materials.append(half_mat)
    sw.uv_layers.active = sw2                                       # saved with UV2 active, UV0 still the render layer
    piece("TST_UVSwitch_1x1_A", [("TST_UVSwitch_1x1_A", sw)], "modelled")
    hid_v = box_verts((0, 0, 0), (1, 1, 1)) + box_verts((0.2, 0.2, 0.2), (0.8, 0.8, 0.8))
    hid_f = BOX_FACES + [tuple(i + 8 for i in f) for f in BOX_FACES]
    piece("TST_Hidden_1x1x1_A", [("TST_Hidden_1x1x1_A", mesh("hidden", hid_v, (), hid_f))], "modelled")
    piece("TST_Solid_1x1x1_A", [("TST_Solid_1x1x1_A", box("solid", (0, 0, 0), (1, 1, 1)))], "modelled")
    off = piece("TST_Offset_1x1x1_A", [("TST_Offset_1x1x1_A", box("off", (0, 0, 0), (1, 1, 1)))], "modelled")
    off.instance_offset = (1.0, 0.0, 0.0)
    piece("TRIM_Skirting_2_A", [("TRIM_Skirting_2_A", box("skirt", (0, 0, 0), (2, 0.02, 0.1)))], "modelled")
    piece("TST_Prop_Free_A", [("TST_Prop_Free_A", box("prop", (-0.5, -0.25, 0), (0.5, 0.25, 0.8)))], "modelled")
    piece("TST_Lamp_Free_A", [("TST_Lamp_Free_A", box("lamp", (-0.2, -0.2, -0.5), (0.2, 0.2, 0)))], "modelled")
    piece("TST_Switch_Free_A", [("TST_Switch_Free_A", box("sw", (-0.04, -0.03, -0.06), (0.04, 0, 0.06)))], "modelled")
    piece("TST_Hinge_Free_A", [("TST_Hinge_Free_A", box("door", (0, -0.02, 0), (0.9, 0.02, 2.1)))], "modelled")
    floor = box("floor", (0, 0, 0), (2, 2, 0.1))
    floor.materials.append(wood)
    floor.materials.append(None)
    piece("TST_Floor_2x2_A", [("TST_Floor_2x2_A", floor)], "textured")
    moved = piece("TST_Moved_1x1x1_A", [("TST_Moved_1x1x1_A", box("moved", (0, 0, 0), (1, 1, 1)))], "modelled")
    moved.objects[0].location = (0.5, 0, 0)
    # LOD1 smaller and the collision shell larger than LOD0, so a render shows which one it drew
    piece("TST_Col_1x1x1_A", [("TST_Col_1x1x1_A_LOD0", box("l0", (0, 0, 0), (1, 1, 1))),
                              ("TST_Col_1x1x1_A_LOD1", box("l1", (0.25, 0.25, 0.25), (0.75, 0.75, 0.75))),
                              ("TST_Col_1x1x1_A_COL", box("col", (-0.25, -0.25, -0.25), (1.25, 1.25, 1.25)))],
          "modelled")
    bevel = piece("TST_Bevel_1x1x1_A", [("TST_Bevel_1x1x1_A", box("bev", (0, 0, 0), (1, 1, 1)))], "modelled")
    mod = bevel.objects[0].modifiers.new("bevel", "BEVEL")
    mod.width, mod.segments = 0.05, 1
    bpy.context.scene.collection.objects.link(bpy.data.objects.new("Stray_Cube", box("stray", (5, 5, 0), (6, 6, 1))))
    save(f["kit"])
    for ob in bpy.context.view_layer.objects:
        ob.select_set(False)
    wall_ob = bpy.data.objects["TST_Wall_2x3_A"]
    wall_ob.select_set(True)
    bpy.context.view_layer.objects.active = wall_ob
    for name in ("TST_Wall_2x3_A.fbx", "Wall.fbx"):
        bpy.ops.export_scene.fbx(filepath=str(f["fbx_dir"] / name), use_selection=True, object_types={"MESH"},
                                 apply_scale_options="FBX_SCALE_ALL", axis_forward="-Z", axis_up="Y",
                                 apply_unit_scale=True, use_space_transform=True, bake_space_transform=True,
                                 mesh_smooth_type="FACE", use_mesh_modifiers=True, path_mode="STRIP")

    reset()
    piece("ABS_Wall_2x3_A", [("ABS_Wall_2x3_A", box("abs", (0, 0, 0), (2, 0.2, 3)))], "textured")
    save(f["kit_abs"])

    # KIT_Tex.blend: two pieces share one material whose texture feeds Base Colour, exported one FBX per piece
    # collection with Path Mode Strip, as blender-to-unity's batch exporter does for kit pieces
    reset()
    save(f["kit_tex"])
    plaster = bpy.data.materials.new("M_TEX_Plaster")
    tex_node = plaster.node_tree.nodes.new("ShaderNodeTexImage")
    tex_node.image = bpy.data.images.load(str(f["tex"]))
    bsdf = next(n for n in plaster.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    plaster.node_tree.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
    for name, hi in (("TEX_Wall_2x3_A", (2, 0.2, 3)), ("TEX_Wall_1x3_A", (1, 0.2, 3))):
        me = box(name, (0, 0, 0), hi)
        grid_uvs(me)
        me.materials.append(plaster)
        piece(name, [(name, me)], "exported")
    save(f["kit_tex"])
    f["fbx_tex"].mkdir()
    for name in ("TEX_Wall_2x3_A", "TEX_Wall_1x3_A"):
        bpy.ops.export_scene.fbx(filepath=str(f["fbx_tex"] / (name + ".fbx")), collection=name, use_selection=False,
                                 use_visible=False, path_mode="STRIP", embed_textures=False, object_types={"MESH"},
                                 use_custom_props=False, global_scale=1.0, apply_unit_scale=True,
                                 apply_scale_options="FBX_SCALE_ALL", axis_forward="-Z", axis_up="Y",
                                 use_space_transform=True, bake_space_transform=True, mesh_smooth_type="FACE",
                                 use_mesh_modifiers=True, use_triangles=True, use_tspace=False, colors_type="NONE",
                                 add_leaf_bones=False, bake_anim=False)

    # KIT_Half.blend: a 0.5 m module; a 0.3 m thick wall is 4x6 (thickness under one module is not in Size)
    reset()
    piece("HLF_Wall_4x6_A", [("HLF_Wall_4x6_A", box("w46", (0, 0, 0), (2, 0.3, 3)))], "modelled")
    piece("HLF_Wall_4x1x6_A", [("HLF_Wall_4x1x6_A", box("w416", (0, 0, 0), (2, 0.3, 3)))], "modelled")
    piece("HLF_Post_1x1x5_A", [("HLF_Post_1x1x5_A", box("post", (0, 0, 0), (0.5, 0.5, 2.5)))], "modelled")
    save(f["kit_half"])

    # KIT_Lit.blend: footprint notes per family (only Free PROP and FOL pieces are told to become probe-lit), UV2
    # folds and Mirror stacks, UV layers a helper or a modifier lacks, and a LOD1 with a bad UV2 layout
    reset()
    for name in ("PROP_Cup_Free_A", "FOL_Fern_Free_A", "ZONE_Shell_Free_A"):
        small = box(name, (-0.05, -0.05, 0), (0.05, 0.05, 0.1))
        grid_uvs(small)
        piece(name, [(name, small)], "uv")
    strip = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 0, 1), (1, 0, 1), (2, 0, 1)]
    fold = mesh("fold", strip, (), [(0, 1, 4, 3), (1, 2, 5, 4)])
    uv_by_vertex(fold, lambda i, co: (0.5 - 0.3 * abs(co.x - 1.0), 0.2 + 0.6 * co.z))  # the second quad folded back
    piece("TST_Fold_2x1_A", [("TST_Fold_2x1_A", fold)], "uv")
    flip = mesh("flip", strip, (), [(0, 1, 4, 3), (4, 5, 2, 1)])                       # second quad's normal flipped
    uv_by_vertex(flip, lambda i, co: (0.1 + 0.4 * co.x, 0.2 + 0.6 * co.z))            # one continuous chart
    piece("TST_Flip_2x1_A", [("TST_Flip_2x1_A", flip)], "uv")
    piece("TST_Arch_Free_A", [("TST_Arch_Free_A", half_arch("arch"))], "uv")
    bpy.data.objects["TST_Arch_Free_A"].modifiers.new("Mirror", "MIRROR")      # its defaults: X axis, merge on
    body = box("guide_body", (0, 0, 0), (1, 1, 1))
    grid_uvs(body)
    guide = mesh("guide", [(0.2, 0.5, 0.5), (0.8, 0.5, 0.5)], [(0, 1)])         # an edges-only helper with 2 UV maps
    guide.uv_layers.new(name="UVMap")
    guide.uv_layers.new(name="UV2")
    piece("TST_Guide_1x1x1_A", [("TST_Guide_1x1x1_A", body), ("TST_Guide_1x1x1_A_guide", guide)], "uv")
    flat = mesh("rebuilt", [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], (), [(0, 1, 2, 3)])
    flat.uv_layers.new(name="UVMap")
    flat.uv_layers.new(name="UV2")
    piece("TST_Rebuilt_Free_A", [("TST_Rebuilt_Free_A", flat)], "uv")
    ng = bpy.data.node_groups.new("Rebuild", "GeometryNodeTree")            # replaces the mesh with a cube: no UVs
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    group_out = ng.nodes.new("NodeGroupOutput")
    ng.links.new(ng.nodes.new("GeometryNodeMeshCube").outputs["Mesh"], group_out.inputs[0])
    bpy.data.objects["TST_Rebuilt_Free_A"].modifiers.new("Rebuild", "NODES").node_group = ng
    lod0 = box("lods0", (0, 0, 0), (1, 1, 1))
    grid_uvs(lod0)
    lod1 = box("lods1", (0.1, 0.1, 0.1), (0.9, 0.9, 0.9))
    grid_uvs(lod1)
    for loop in lod1.loops:                                    # LOD1's UV2: every face on one quad, out to u 1.3
        lod1.uv_layers["UV2"].uv[loop.index].vector = [(0.1, 0.1), (1.3, 0.1), (1.3, 0.9), (0.1, 0.9)][loop.index % 4]
    piece("TST_Lods_1x1x1_A", [("TST_Lods_1x1x1_A_LOD0", lod0), ("TST_Lods_1x1x1_A_LOD1", lod1)], "uv")
    # the same 0.025 UV gap on LOD0 and LOD1: 3.3 texels at LOD0's 133 px footprint (60 texels/m), 1.7 at LOD1's half
    piece("TST_Lodgap_2x2_A", [("TST_Lodgap_2x2_A_LOD%d" % n, two_charts("lodgap%d" % n, (0.05, 0.45), (0.475, 0.95)))
                               for n in (0, 1)], "uv")
    # a 2 x 1 x 2 m stall (16 m2, b 0.49) with LOD1 and LOD2: 114.3, 57.1 and 28.6 px at 20 texels/m
    stall = [("PROP_Stall_Free_A_LOD%d" % n, box("stall%d" % n, (-1, -0.5, 0), (1, 0.5, 2))) for n in range(3)]
    for _, me in stall:
        grid_uvs(me)
    piece("PROP_Stall_Free_A", stall, "uv")
    piece("TST_Sparse_Free_A", [("TST_Sparse_Free_A", two_charts("sparse", (0.05, 0.15), (0.85, 0.95)))], "uv")
    # UV2 box fill 0.3 on LOD0 (120 px at 60 texels/m and lightmap_scale 0.9) and on LOD2 (30 px)
    piece("TST_Fill_2x2_A", [("TST_Fill_2x2_A_LOD%d" % n, two_charts("fill%d" % n, (0.05, 0.185), (0.815, 0.95)))
                             for n in (0, 2)], "uv")
    save(f["kit_lit"])                                         # TST_Sparse: two thin charts fill 22% of their box

    # KIT_Bakery.blend, measured at 20 texels/m: Bakery's footprint against Unity's (issue #10)
    reset()
    # a 0.015 UV gap at Scale In Lightmap 4: 2.7 texels at Unity's 177.8 px, 1.8 at Bakery's 119.0
    piece("TST_Bgap_2x2_A", [("TST_Bgap_2x2_A", two_charts("bgap", (0.05, 0.49), (0.505, 0.95)))], "uv")
    # LOD0 and LOD1 of the same area: Bakery sizes each by its own area, Unity halves LOD1
    piece("TST_Blod_2x2_A", [("TST_Blod_2x2_A_LOD%d" % n, two_charts("blod%d" % n, (0.05, 0.4), (0.6, 0.95)))
                             for n in (0, 1)], "uv")
    strip = mesh("bstrip", [(0, 0, 0), (4, 0, 0), (4, 1, 0), (0, 1, 0)], (), [(0, 1, 2, 3)])
    strip.uv_layers.new(name="UVMap")
    uv2 = strip.uv_layers.new(name="UV2")
    for li, uv in zip(strip.polygons[0].loop_indices, [(0.4, 0.05), (0.6, 0.05), (0.6, 0.95), (0.4, 0.95)]):
        uv2.uv[li].vector = uv
    piece("TST_Bstrip_4x1_A", [("TST_Bstrip_4x1_A", strip)], "uv")         # UV2 bounds 0.2 x 0.9: short side 0.2
    # a 4 x 4 m panel of 64 charts packed small (fill 0.08): 7.5 effective texels/m under Bakery, under its 10
    panel = mesh("bmany", [(0.5 * i, 0.5 * j, 0) for j in range(9) for i in range(9)], (),
                 [(i + 9 * j, i + 1 + 9 * j, i + 10 + 9 * j, i + 9 + 9 * j) for j in range(8) for i in range(8)])
    grid_uvs(panel, m=0.042, lo=0.05, hi=0.95)
    piece("TST_Bmany_4x4_A", [("TST_Bmany_4x4_A", panel)], "uv")
    flat = mesh("bnone", [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)], (), [(0, 1, 2, 3)])
    flat.uv_layers.new(name="UVMap")
    piece("TST_Bnone_2x2_A", [("TST_Bnone_2x2_A", flat)], "modelled")    # no UV2 yet: the planning estimate
    save(f["kit_bakery"])

    # KIT_Hidden.blend: the half arch with a default Mirror (its UV2 halves stack) in the five states a kit author
    # isolates pieces with; as saved, the view layer evaluates only the first two
    reset()
    for state in ("Visible", "Hidden", "Excluded", "CollOff", "ObjOff"):
        name = "PROP_Arch%s_Free_A" % state
        coll = piece(name, [(name, half_arch(name.lower()))], "uv")
        ob = bpy.data.objects[name]
        ob.modifiers.new("Mirror", "MIRROR")
        if state == "Hidden":
            ob.hide_set(True)
        elif state == "Excluded":
            bpy.context.view_layer.layer_collection.children[name].exclude = True
        elif state == "CollOff":
            coll.hide_viewport = True
        elif state == "ObjOff":
            ob.hide_viewport = True
    save(f["kit_hidden"])

    # T-RENAME: PROP_Stall_Free_A renamed PROP_MarketStall_Free_A. before/ places it three times with placement ids;
    # good/ re-points those instances (ids kept); replaced/ deletes them and places new ones under the same names (ids
    # gone); renamed/ places new ones under new names
    for mode in ("before", "good", "replaced", "renamed"):
        sub = f["rename"] / mode
        sub.mkdir(parents=True)
        name = "PROP_Stall_Free_A" if mode == "before" else "PROP_MarketStall_Free_A"
        reset()
        piece(name, [(name, box(name.lower(), (-1, -0.5, 0), (1, 0.5, 2)))], "textured")
        save(sub / "KIT_Props.blend")
        reset()
        save(sub / "MASTER.blend")
        stall_l = link(sub / "KIT_Props.blend", [name])[name]
        for i, (obname, loc, rz) in enumerate((("stall_1", (2, 3, 0), 0), ("stall_2", (5, 3, 0), 90),
                                               ("stall_3", (8, 6, 0), 180))):
            ob = instance(obname + (".001" if mode == "renamed" else ""), stall_l, loc, rot=(0, 0, rz))
            if mode in ("before", "good"):
                ob["placement_id"] = "pl-%04d" % (101 + i)
        save(sub / "MASTER.blend")

    # KIT_Dense.blend: 4,608 one-face UV2 charts (a Lightmap Pack's worst case), for the layout test's running time
    reset()
    nx, ny = 96, 48
    dense = mesh("dense", [(0.05 * i, 0.0, 0.05 * j) for j in range(ny + 1) for i in range(nx + 1)], (),
                 [(j * (nx + 1) + i, j * (nx + 1) + i + 1, (j + 1) * (nx + 1) + i + 1, (j + 1) * (nx + 1) + i)
                  for j in range(ny) for i in range(nx)])
    grid_uvs(dense, m=0.002)                                    # charts 0.004 apart, 0.102 from the tile edge
    piece("TST_Dense_Free_A", [("TST_Dense_Free_A", dense)], "uv")
    save(f["kit_dense"])

    # ASM_Booth_A.blend: its own assembly plus a second one
    reset()
    save(f["asm"])
    wall_l = link(f["kit"], ["TST_Wall_2x3_A"])["TST_Wall_2x3_A"]
    booth = bpy.data.collections.new("ASM_Booth_A")
    bpy.context.scene.collection.children.link(booth)
    instance("w1", wall_l, (0, 0, 0), parent=booth)
    instance("w2", wall_l, (2, 0, 0), parent=booth)
    extra = bpy.data.collections.new("ASM_Extra_A")
    bpy.context.scene.collection.children.link(extra)
    instance("w3", wall_l, (0, 2, 0), parent=extra)
    save(f["asm"])

    # ASM_Shift_A.blend: an assembly saved with a non-zero instance_offset
    reset()
    save(f["asm_shift"])
    shift = bpy.data.collections.new("ASM_Shift_A")
    bpy.context.scene.collection.children.link(shift)
    instance("s1", link(f["kit"], ["TST_Wall_2x3_A"])["TST_Wall_2x3_A"], parent=shift)
    shift.instance_offset = (0.5, 0.0, 0.0)
    save(f["asm_shift"])

    # MASTER.blend: good and bad placements, an appended assembly, a local piece, an absolute library
    reset()
    save(f["master"])
    kit = link(f["kit"], ["TST_Wall_2x3_A", "TST_Bevel_1x1x1_A", "TST_Col_1x1x1_A", "TST_Offset_1x1x1_A",
                          "TRIM_Skirting_2_A"])
    booth_l = link(f["asm"], ["ASM_Booth_A"])["ASM_Booth_A"]
    shift_l = link(f["asm_shift"], ["ASM_Shift_A"])["ASM_Shift_A"]
    abs_wall = link(f["kit_abs"], ["ABS_Wall_2x3_A"], relative=False)["ABS_Wall_2x3_A"]
    wall_l = kit["TST_Wall_2x3_A"]
    zone = bpy.data.collections.new("zone")
    bpy.context.scene.collection.children.link(zone)
    instance("wall_ok", wall_l, (1, 1, 0), parent=zone)["placement_id"] = "id-ok"
    instance("wall_tilt", wall_l, (3, 1, 0), rot=(30, 0, 0), parent=zone)
    instance("wall_scaled", wall_l, (5, 1, 0), scale=(1.5, 1.5, 1.5), parent=zone)
    instance("wall_rot45", wall_l, (7, 1, 0), rot=(0, 0, 45), parent=zone)
    instance("wall_offgrid", wall_l, (9.37, 1, 0), parent=zone)
    instance("wall_west", wall_l, (11, 1, 0), rot=(0, 0, -90), parent=zone)
    instance("booth", booth_l, (0, 4, 0), rot=(0, 0, 90), parent=zone)
    instance("bevel", kit["TST_Bevel_1x1x1_A"], (0, 8, 0), parent=zone)
    instance("abs_wall", abs_wall, (4, 8, 0), parent=zone)
    instance("col_piece", kit["TST_Col_1x1x1_A"], (20, 20, 0), parent=zone)      # alone, for the render test
    instance("offset_piece", kit["TST_Offset_1x1x1_A"], (14, 1, 0), parent=zone)
    instance("trim", kit["TRIM_Skirting_2_A"], (1, 0.25, 0), parent=zone)         # on a 0.25 m sub-module
    instance("shifted", shift_l, (30, 30, 0), parent=zone)
    copy = bpy.data.collections.new("ASM_Copy_A")                  # an appended assembly, never in the scene tree
    instance("inner", wall_l, parent=copy)
    instance("asm_copy", copy, (2.37, 12, 0), rot=(0, 0, 45), parent=zone)
    piece("TST_Slab_2x2_A", [("TST_Slab_2x2_A", box("slab", (0, 0, 0), (2, 2, 0.1)))], "modelled")
    shadow = bpy.data.collections.new("TST_Bevel_1x1x1_A")         # same name as the linked piece (names are
    bpy.context.scene.collection.children.link(shadow)             # unique per library, so it keeps the name)
    f["shadow_name"] = shadow.name
    ref = bpy.data.collections.new("REF")
    bpy.context.scene.collection.children.link(ref)
    ref.objects.link(bpy.data.objects.new("REF_Figure_1.6m", box("fig", (0, 0, 0), (0.4, 0.2, 1.6))))
    bpy.context.scene.collection.objects.link(bpy.data.objects.new("Stray_Plane", box("sp", (0, 0, 0), (1, 1, 0.01))))
    save(f["master"])
    return f


# ---- running qa_measure -------------------------------------------------------------------------------------------

def run_qa(blend, args, json_path=None, module=True):
    """Run qa_measure in a fresh headless Blender; returns (process, report or None). A run that measures a file gets
    --module 1.0 unless it passes its own (or module=False)."""
    args = [str(a) for a in args]
    if module and (blend or "--import-fbx" in args) and "--module" not in args:
        args = ["--module", "1.0"] + args
    cmd = [BLENDER, "-b", "--factory-startup"] + ([str(blend)] if blend else [])
    cmd += ["--python-exit-code", "1", "--python", str(QA), "--"] + args
    if json_path:
        cmd += ["--json", str(json_path)]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    rep = None
    if json_path and Path(json_path).exists():
        rep = json.loads(Path(json_path).read_text(encoding="utf-8"))
    return p, rep


class Runs:
    """Each qa_measure run once, on first use; a run that fails raises in every case that needs it."""

    def __init__(self, d, f):
        self.d, self.f, self.cache = d, f, {}

    def get(self, key):
        if key not in self.cache:
            try:
                self.cache[key] = getattr(self, "_" + key)()
            except Exception as exc:                                  # remembered, re-raised per case
                self.cache[key] = exc
        if isinstance(self.cache[key], Exception):
            raise AssertionError("run %s failed: %s" % (key, self.cache[key]))
        return self.cache[key]

    def _ok(self, blend, args, name):
        p, rep = run_qa(blend, args, self.d / (name + ".json"))
        if p.returncode != 0 or rep is None:
            raise RuntimeError("exit %s: %s" % (p.returncode, (p.stdout + p.stderr)[-2000:]))
        return rep

    def _kit(self):
        return self._ok(self.f["kit"], ["--piece-tris", '{"TST": 1000, "TST_Wall_2x3_A": 4}',
                                        "--lightmap-texels", "20", "--lightmap-scale", '{"TST_Wall_2x3_A": 0.5}',
                                        "--texel-map", "1024"], "kit")

    def _kit_split(self):
        return self._ok(self.f["kit"], ["--expect-status", "modelled", "--pieces", "TST_Wall_2x3_A,TST_Prop_*,NOPE_*"],
                        "kit_split")

    def _kit_probe(self):
        return self._ok(self.f["kit"], ["--lightmap-texels", "20", "--probe-lit", "TST_Lap_2x2_A"], "kit_probe")

    def _uv_default(self):
        return self.shot("uv_default", self.f["kit"], ["--isolate", "TST_UVSwitch_1x1_A", "--render", "front",
                                                       "--center", "0.5", "0", "0.5", "--extent", "1", "1",
                                                       "--px-per-m", "40", "--color", "texture", "--light", "flat"])

    def _uv_uv2(self):
        return self.shot("uv_uv2", self.f["kit"], ["--isolate", "TST_UVSwitch_1x1_A", "--render", "front",
                                                   "--center", "0.5", "0", "0.5", "--extent", "1", "1",
                                                   "--px-per-m", "40", "--color", "texture", "--light", "flat",
                                                   "--uv-layer", "UV2"])

    def section(self, name, piece):
        return self.shot(name, self.f["kit"], ["--isolate", piece, "--render", "front", "--center", "0.5", "0.5",
                                               "0.5", "--extent", "1.2", "1.2", "--px-per-m", "50", "--clip", "0.05",
                                               "--wire", "0.03"])

    def _section_solid(self):
        return self.section("section_solid", "TST_Solid_1x1x1_A")

    def _section_hidden(self):
        return self.section("section_hidden", "TST_Hidden_1x1x1_A")

    def _kit_half(self):
        return self._ok(self.f["kit_half"], ["--module", "0.5"], "kit_half")

    def _lit(self):
        return self._ok(self.f["kit_lit"], ["--expect-status", "uv", "--lightmap-texels", "60",
                                            "--lightmap-scale", '{"TST_Fill_2x2_A": 0.9}'], "lit")

    def _lit_split(self):
        return self._ok(self.f["kit_lit"], ["--lightmap-texels", "20", "--pieces", "PROP_*,FOL_*",
                                            "--probe-lit", "PROP_Cup_Free_A,NOPE_*"], "lit_split")

    def bakery_run(self, name, lightmapper, *extra):
        return self._ok(self.f["kit_bakery"], ["--expect-status", "uv", "--lightmap-texels", "20", "--lightmap-scale",
                                               '{"TST_Bgap_2x2_A": 4}', "--lightmapper", lightmapper] + list(extra),
                        name)

    def _bakery(self):
        return self.bakery_run("bakery", "bakery")

    def _bakery_unity(self):
        return self.bakery_run("bakery_unity", "progressive")

    def _bakery_probe(self):
        return self.bakery_run("bakery_probe", "bakery", "--probe-lit", "TST_Bmany_4x4_A")

    def _hidden(self):
        return self._ok(self.f["kit_hidden"], ["--expect-status", "uv"], "hidden")

    def _hidden_states(self):
        """Visibility states before and after measure() in one session (they must come back), and its tris."""
        p = subprocess.run([BLENDER, "-b", "--factory-startup", str(self.f["kit_hidden"]), "--python-exit-code", "1",
                            "--python-expr", STATES_EXPR % str(QA)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300)
        line = next((l for l in p.stdout.splitlines() if l.startswith("QA_STATES ")), None)
        if p.returncode != 0 or line is None:
            raise RuntimeError("exit %s: %s" % (p.returncode, (p.stdout + p.stderr)[-2000:]))
        return json.loads(line[len("QA_STATES "):])

    def _rename_before(self):
        return self._ok(self.f["rename"] / "before" / "MASTER.blend", [], "rename_before")

    def rename(self, mode):
        self.get("rename_before")
        return self._ok(self.f["rename"] / mode / "MASTER.blend",
                        ["--compare-placements", self.d / "rename_before.json"], "rename_" + mode)

    def _rename_good(self):
        return self.rename("good")

    def _rename_replaced(self):
        return self.rename("replaced")

    def _rename_renamed(self):
        return self.rename("renamed")

    def _dense(self):
        start = time.perf_counter()
        rep = self._ok(self.f["kit_dense"], ["--expect-status", "uv", "--lightmap-texels", "20"], "dense")
        return rep, time.perf_counter() - start

    def _master_sub(self):
        return self._ok(self.f["master"], ["--sub-module", "0.25"], "master_sub")

    def _fbx_tex(self):                       # a quoted glob, expanded by qa_measure itself
        return self._ok(None, ["--import-fbx", str(self.f["fbx_tex"] / "*.fbx")], "fbx_tex")

    def shot(self, name, blend, args):
        """A render run: (report, png)."""
        png = self.d / (name + ".png")
        return self._ok(blend, list(args) + ["--png", png], name), png

    def _col_default(self):
        return self.shot("col_default", self.f["kit"], ["--isolate", "TST_Col_1x1x1_A", "--render", "front",
                                                        "--center", "0.5", "0", "0.5", "--extent", "2", "2", "--color", "material"])

    def _col_show(self):
        return self.shot("col_show", self.f["kit"], ["--isolate", "TST_Col_1x1x1_A", "--show-collision", "--render",
                                                     "front", "--center", "0.5", "0", "0.5", "--extent", "2", "2", "--color", "material"])

    def _col_lod1(self):
        return self.shot("col_lod1", self.f["kit"], ["--isolate", "TST_Col_1x1x1_A", "--lod", "1", "--render",
                                                     "front", "--center", "0.5", "0", "0.5", "--extent", "2", "2", "--color", "material"])

    def _col_hidden(self):
        return self.shot("col_hidden", self.f["kit"], ["--isolate", "TST_Col_1x1x1_A", "--hide-object", "*_LOD0",
                                                       "--render", "front", "--center", "0.5", "0", "0.5",
                                                       "--extent", "2", "2", "--color", "material"])

    def _master_col(self):
        return self.shot("master_col", self.f["master"], ["--render", "top", "--center", "20.5", "20.5",
                                                          "--extent", "2", "2", "--color", "material"])

    def _wire_off(self):
        return self.shot("wire_off", self.f["kit"], ["--isolate", "TST_Wall_2x3_A", "--render", "front", "--center",
                                                     "1", "0", "1.5", "--extent", "3", "4", "--color", "material",
                                                     "--light", "flat"])

    def _wire_on(self):
        return self.shot("wire_on", self.f["kit"], ["--isolate", "TST_Wall_2x3_A", "--render", "front", "--center",
                                                    "1", "0", "1.5", "--extent", "3", "4", "--light", "flat", "--wire"])

    def _kit_modelled(self):
        return self._ok(self.f["kit"], ["--expect-status", "modelled"], "kit_modelled")

    def _asm(self):
        return self._ok(self.f["asm"], [], "asm")

    def _master(self):
        return self._ok(self.f["master"], [], "master")

    def _master_textured(self):
        return self._ok(self.f["master"], ["--expect-status", "textured"], "master_textured")

    def _master_compare(self):
        prev = json.loads(json.dumps(self.get("master")))
        pl = prev["placements"]
        next(p for p in pl if p["object"] == "wall_ok")["pos"][0] -= 1.0
        prev["placements"] = [p for p in pl if p["object"] != "wall_west"] + [
            {"object": "ghost", "asset": "TST_Wall_2x3_A", "id": None, "pos": [0, 0, 0], "rot_z": 0}]
        path = self.d / "prev_master.json"
        path.write_text(json.dumps(prev), encoding="utf-8")
        return self._ok(self.f["master"], ["--compare-placements", path], "master_compare")

    def _fbx(self):
        return self._ok(None, ["--import-fbx", self.f["fbx_dir"] / "TST_Wall_2x3_A.fbx",
                               self.f["fbx_dir"] / "Wall.fbx"], "fbx")

    def _render_top(self):
        png = self.d / "top.png"
        rep = self._ok(self.f["master"], ["--render", "top", "--center", "6", "7", "--extent", "16", "18",
                                          "--png", png, "--overlay", self.f["svg"], "--overlay-out",
                                          self.d / "top_overlay.svg", "--hide-collection", "REF"], "render_top")
        return rep, png

    def _render_view(self):
        png = self.d / "view.png"
        rep = self._ok(self.f["master"], ["--view", "1", "-6", "1.7", "1", "1", "1", "24", "--png", png,
                                          "--color", "texture", "--light", "flat"], "render_view")
        return rep, png

    def _images(self):
        return self._ok(None, ["--image-stats", self.f["dark"], "--gain", "4",
                               "--tile-seam", self.f["seamless"], self.f["seamed"]], "images")


# ---- cases ----------------------------------------------------------------------------------------------------------

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def check(cond, why):
    if not cond:
        raise AssertionError(why)


def has(problems, *parts):
    return any(all(p in line for p in parts) for line in problems)


def piece_of(rep, name):
    return next(p for p in rep["pieces"] if p["piece"] == name)


@case
def misnamed_piece_reported(r):
    rep = r.get("kit")
    check("TST_Wall_2x3" in rep["unnamed_collections"], "unnamed_collections %s" % rep["unnamed_collections"])
    check(has(rep["problems"], "TST_Wall_2x3 holds meshes"), "no PROBLEM line for the misnamed collection")
    check(all(p["piece"] != "TST_Wall_2x3" for p in rep["pieces"]), "a misnamed collection measured as a piece")


@case
def clean_wall_measured(r):
    w = piece_of(r.get("kit"), "TST_Wall_2x3_A")
    ob = w["objects"]["TST_Wall_2x3_A"]
    check(w["size_ok"] and w["pivot_ok"] and not w["transform_issues"], "wall %s" % w)
    check(w["lod0_tris"] == 12 and ob["uv_layers"] == 2 and abs(ob["area_m2"] - 14.0) < 1e-3, "wall %s" % ob)
    check(not w["bad_materials"] and w["coplanar_overlaps"] == 0, "wall %s" % w)
    check(ob["uv2_bbox_share"] == 0.49, "uv2_bbox_share %s" % ob.get("uv2_bbox_share"))
    check(abs(ob["lightmap_px"] - 0.5 * 20 * math.sqrt(14.0 / 0.49)) < 0.2, "lightmap_px %s" % ob.get("lightmap_px"))
    grid = piece_of(r.get("kit"), "TST_Grid_2x2_A")
    gob = grid["objects"]["TST_Grid_2x2_A"]
    check("uv2_bbox_share" not in gob and abs(gob["lightmap_px"] - 20 * math.sqrt(4.0 / 0.85)) < 0.2,
          "no UV2: the 0.85 planning estimate at scale 1 expected: %s" % gob)
    check(grid["bad_materials"] == [], "M_TST_Brick_Dark rejected: %s" % grid["bad_materials"])
    check(gob["uv"]["UVMap"]["bounds"] == [0.0, 0.0, 0.5, 0.5] and gob["uv0_px_per_m"] == 256.0
          and gob["uv0_px_per_m_range"] == [256.0, 256.0], "UV0 data %s" % gob)


def notes_of(rep, piece):
    return [n for n in rep["notes"] if n.startswith(piece + "/")]


@case
def small_footprints_noted(r):
    kit = r.get("kit")
    wall, switch = notes_of(kit, "TST_Wall_2x3_A"), notes_of(kit, "TST_Switch_Free_A")
    check(wall and all("stays lightmapped" in n for n in wall), kit["notes"])
    check(switch and all("stays lightmapped" in n and "probe-lit" not in n for n in switch),
          "a Free piece outside PROP and FOL follows the grid-piece rule: %s" % switch)
    check(not has(kit["problems"], "lightmap footprint"), "a footprint note became a PROBLEM line")


@case
def footprint_notes_by_family(r):
    lit, split = r.get("lit"), r.get("lit_split")
    for name in ("PROP_Cup_Free_A", "FOL_Fern_Free_A"):
        got = notes_of(lit, name)
        check(got and all("make it probe-lit" in n and "lighting_states" in n for n in got), (name, got))
    zone = notes_of(lit, "ZONE_Shell_Free_A")
    check(zone and all("stays lightmapped" in n and "probe-lit" not in n for n in zone),
          "a Free-sized ZONE shell follows the grid-piece rule: %s" % zone)
    check(not notes_of(split, "PROP_Cup_Free_A"), "a --probe-lit piece got a footprint note: %s" % split["notes"])
    check(notes_of(split, "FOL_Fern_Free_A"), "a piece in --pieces lost its note: %s" % split["notes"])
    check(not notes_of(split, "ZONE_Shell_Free_A"), "a piece outside --pieces got a note: %s" % split["notes"])


@case
def uv2_folds_and_mirror_stacks(r):
    lit = r.get("lit")
    fold = piece_of(lit, "TST_Fold_2x1_A")["objects"]["TST_Fold_2x1_A"]
    check(fold["uv2_charts"] == 2 and fold["uv2_overlaps"] == 1, "a UV2 folded over its shared edge: %s" % fold)
    check(has(lit["problems"], "TST_Fold_2x1_A/TST_Fold_2x1_A: 1 pairs of UV2 charts overlap"), "fold passed")
    flip = piece_of(lit, "TST_Flip_2x1_A")["objects"]["TST_Flip_2x1_A"]
    check(flip["uv2_charts"] == 1 and flip["uv2_overlaps"] == 0, "flipped face, continuous UV2 split: %s" % flip)
    check(not has(lit["problems"], "TST_Flip_2x1_A"), "the flipped-normal control was flagged")
    arch = piece_of(lit, "TST_Arch_Free_A")["objects"]["TST_Arch_Free_A"]
    check(arch["tris"] == 48 and arch["uv2_charts"] == 2 and arch["uv2_overlaps"] == 1,
          "a Mirror modifier at its defaults stacks the halves: %s" % arch)
    check(has(lit["problems"], "TST_Arch_Free_A/TST_Arch_Free_A: 1 pairs of UV2 charts overlap"), "stack passed")


@case
def uv_layers_counted_as_exported(r):
    lit = r.get("lit")                         # these meshes crashed the run before (IndexError in problems())
    guide = piece_of(lit, "TST_Guide_1x1x1_A")["objects"]["TST_Guide_1x1x1_A_guide"]
    check(guide["tris"] == 0 and "lightmap_px" not in guide, "edges-only helper: %s" % guide)
    check(has(lit["problems"], "TST_Guide_1x1x1_A/TST_Guide_1x1x1_A_guide: no UV2", "(it has no faces)"),
          "the edges-only helper's PROBLEM line")
    check(not any(n.startswith("TST_Guide_1x1x1_A/TST_Guide_1x1x1_A_guide") for n in lit["notes"]),
          "a wire helper got a footprint note")
    rebuilt = piece_of(lit, "TST_Rebuilt_Free_A")["objects"]["TST_Rebuilt_Free_A"]
    check(rebuilt["tris"] == 12 and rebuilt["uv_layers"] == 0, "a Geometry Nodes rebuild drops the UVs: %s" % rebuilt)
    check(has(lit["problems"], "TST_Rebuilt_Free_A/TST_Rebuilt_Free_A: no UV2"), "a dropped UV2 passed")


@case
def lod_uv2_layout_checked(r):
    lit = r.get("lit")
    probs = lit["problems"]
    check(has(probs, "TST_Lods_1x1x1_A/TST_Lods_1x1x1_A_LOD1: UV2 outside 0-1"), "LOD1 out of the tile passed")
    check(has(probs, "TST_Lods_1x1x1_A/TST_Lods_1x1x1_A_LOD1:", "pairs of UV2 charts overlap"), "LOD1 overlaps passed")
    check(not has(probs, "TST_Lods_1x1x1_A/TST_Lods_1x1x1_A_LOD0"), "the good LOD0 was flagged: %s" % probs)
    ns = {}
    exec(compile(QA.read_text(encoding="utf-8"), str(QA), "exec"), ns)
    check(ns["UV2_LAYOUT_ALL_LODS"] is True and ns["PROBE_LIT_FAMILIES"] == ("PROP", "FOL"), "constants")
    lod0_only = ns["problems"](lit, expect_status="uv", all_lods=False)
    check(not has(lod0_only, "_LOD1:", "UV2"), "all_lods=False still checked a LOD1 layout: %s" % lod0_only)
    one_lod = ns["problems"](lit, expect_status="uv", probe_lit=["TST_Lods_1x1x1_A_LOD1"])
    check(not has(one_lod, "TST_Lods_1x1x1_A/TST_Lods_1x1x1_A_LOD1"), "a LOD marked probe-lit was still checked")


@case
def lod_footprint_halves(r):
    lit = r.get("lit")
    objs = piece_of(lit, "TST_Lodgap_2x2_A")["objects"]
    l0, l1 = objs["TST_Lodgap_2x2_A_LOD0"], objs["TST_Lodgap_2x2_A_LOD1"]
    check(abs(l0["lightmap_px"] - 60 * math.sqrt(4.0 / 0.81)) < 0.2 and abs(l1["lightmap_px"] - l0["lightmap_px"] / 2)
          < 0.1, "LOD1's footprint should be half LOD0's (0.5^n): %s vs %s" % (l1["lightmap_px"], l0["lightmap_px"]))
    check(l0["uv2_min_gap_texels"] >= 2 and l1["uv2_min_gap_texels"] < 2, (l0, l1))
    check(has(lit["problems"], "TST_Lodgap_2x2_A/TST_Lodgap_2x2_A_LOD1: UV2 charts"), "LOD1's gap passed at LOD0's scale")
    check(not has(lit["problems"], "TST_Lodgap_2x2_A/TST_Lodgap_2x2_A_LOD0"), "LOD0's 3.3 texel gap was flagged")


@case
def lod0_decides_the_footprint_note(r):
    split = r.get("lit_split")
    objs = piece_of(split, "PROP_Stall_Free_A")["objects"]
    px = [objs["PROP_Stall_Free_A_LOD%d" % n]["lightmap_px"] for n in range(3)]
    check(abs(px[0] - 114.3) < 0.2 and abs(px[1] - 57.1) < 0.2 and abs(px[2] - 28.6) < 0.2, "footprints %s" % px)
    check(not notes_of(split, "PROP_Stall_Free_A"),
          "LOD0 at 114 px decides for the piece; LOD1+ follow it: %s" % notes_of(split, "PROP_Stall_Free_A"))
    check(has(split["problems"], "--probe-lit NOPE_* matches no piece or LOD object"), "an unmatched --probe-lit passed")
    check(not has(split["problems"], "--probe-lit PROP_Cup_Free_A"), "a matching --probe-lit reported")


@case
def uv2_box_fill_noted(r):
    lit = r.get("lit")
    sparse = piece_of(lit, "TST_Sparse_Free_A")["objects"]["TST_Sparse_Free_A"]
    check(abs(sparse["uv2_box_fill"] - 0.2222) < 1e-3, sparse)
    check(any("fill 22% of their bounding box" in n for n in notes_of(lit, "TST_Sparse_Free_A")), lit["notes"])
    flip = piece_of(lit, "TST_Flip_2x1_A")["objects"]["TST_Flip_2x1_A"]
    check(flip["uv2_box_fill"] == 1.0 and not notes_of(lit, "TST_Flip_2x1_A"), "a strip that fills its box: %s" % flip)
    objs = piece_of(lit, "TST_Fill_2x2_A")["objects"]
    lod0, lod2 = objs["TST_Fill_2x2_A_LOD0"], objs["TST_Fill_2x2_A_LOD2"]
    check(abs(lod0["uv2_box_fill"] - 0.3) < 1e-3 and abs(lod2["uv2_box_fill"] - 0.3) < 1e-3
          and abs(lod0["lightmap_px"] - 120.0) < 0.2 and abs(lod2["lightmap_px"] - 30.0) < 0.2, (lod0, lod2))
    fill = notes_of(lit, "TST_Fill_2x2_A")
    check(any(n.startswith("TST_Fill_2x2_A/TST_Fill_2x2_A_LOD0: UV2 charts fill 30%") for n in fill),
          "a 120 px UV2 at fill 0.3 should be noted: %s" % fill)
    check(not any("_LOD2" in n for n in fill), "a 30 px LOD2 is the 64 px rule's, not box fill's: %s" % fill)


def bakery_side(area, scale=1.0):
    """Bakery's rect side at 20 texels/m: texels_per_m x sqrt(2 x area x Scale In Lightmap)."""
    return 20 * math.sqrt(2 * area * scale)


@case
def bakery_footprints(r):
    bk, un = r.get("bakery"), r.get("bakery_unity")
    check(bk["lightmapper"] == "bakery" and un["lightmapper"] == "unity", "progressive should read as unity: %s, %s"
          % (bk["lightmapper"], un["lightmapper"]))
    gap_b = piece_of(bk, "TST_Bgap_2x2_A")["objects"]["TST_Bgap_2x2_A"]
    gap_u = piece_of(un, "TST_Bgap_2x2_A")["objects"]["TST_Bgap_2x2_A"]
    check(abs(gap_b["lightmap_px"] - (bakery_side(4, 4) - 6) / 0.9) < 0.2
          and abs(gap_u["lightmap_px"] - 20 * math.sqrt(4 / 0.81) * 4) < 0.2, (gap_b, gap_u))
    check(gap_u["uv2_min_gap_texels"] >= 2 and gap_b["uv2_min_gap_texels"] < 2, (gap_u, gap_b))
    check(has(bk["problems"], "TST_Bgap_2x2_A/TST_Bgap_2x2_A: UV2 charts", "apart")
          and not has(un["problems"], "TST_Bgap_2x2_A"),
          "a gap Unity's footprint passes at Scale In Lightmap 4 must fail at Bakery's: %s" % bk["problems"])
    strip = piece_of(bk, "TST_Bstrip_4x1_A")["objects"]["TST_Bstrip_4x1_A"]
    ustrip = piece_of(un, "TST_Bstrip_4x1_A")["objects"]["TST_Bstrip_4x1_A"]
    check(strip["uv2_short_side"] == 0.2 and abs(strip["lightmap_px"] - (bakery_side(4) - 6) / 0.2) < 0.3
          and abs(ustrip["lightmap_px"] - 20 * math.sqrt(4 / 0.18)) < 0.2,
          "Bakery maps its rect onto the UV2 bounds' short side: %s vs %s" % (strip, ustrip))
    objs, uobjs = piece_of(bk, "TST_Blod_2x2_A")["objects"], piece_of(un, "TST_Blod_2x2_A")["objects"]
    l0, l1 = objs["TST_Blod_2x2_A_LOD0"], objs["TST_Blod_2x2_A_LOD1"]
    check(abs(l0["lightmap_px"] - (bakery_side(4) - 6) / 0.9) < 0.2 and l1["lightmap_px"] == l0["lightmap_px"]
          and abs(uobjs["TST_Blod_2x2_A_LOD1"]["lightmap_px"] - 10 * math.sqrt(4 / 0.81)) < 0.2,
          "Bakery has no LOD factor, Unity 0.5^n: %s, %s, %s" % (l0, l1, uobjs["TST_Blod_2x2_A_LOD1"]))
    none = piece_of(bk, "TST_Bnone_2x2_A")["objects"]["TST_Bnone_2x2_A"]
    check(abs(none["lightmap_px"] - (bakery_side(4) - 6) / math.sqrt(0.85)) < 0.2
          and "effective_texels_per_m" not in none, "before UV2 exists: square bounds of share 0.85: %s" % none)
    p, _ = run_qa(r.f["kit_bakery"], ["--lightmap-texels", "20", "--lightmapper", "beast"])
    check(p.returncode != 0 and "invalid choice" in p.stdout + p.stderr, (p.stdout + p.stderr)[-500:])


@case
def bakery_effective_density_gate(r):
    bk, un, probe = r.get("bakery"), r.get("bakery_unity"), r.get("bakery_probe")
    a = 64 * (0.9 / 8 - 2 * 0.042) ** 2                       # the 64 charts' UV area; their box is 0.816 square
    many = piece_of(bk, "TST_Bmany_4x4_A")["objects"]["TST_Bmany_4x4_A"]
    umany = piece_of(un, "TST_Bmany_4x4_A")["objects"]["TST_Bmany_4x4_A"]
    eff = (bakery_side(16) - 6) / 0.816 * math.sqrt(a / 16)
    check(abs(many["effective_texels_per_m"] - eff) < 0.05 and many["effective_texels_min"] == 10.0, (eff, many))
    check(abs(umany["effective_texels_per_m"] - 20 * math.sqrt(a / 0.816 ** 2)) < 0.05
          and "effective_texels_min" not in umany, "Unity: texels_per_m x sqrt(box fill), no gate: %s" % umany)
    check(has(bk["problems"], "TST_Bmany_4x4_A/TST_Bmany_4x4_A: effective lightmap density", "under 10.0"),
          "a many-chart UV2 under Bakery's gate passed: %s" % bk["problems"])
    check(not notes_of(bk, "TST_Bmany_4x4_A"), "the gate's PROBLEM replaces the box-fill note: %s" % bk["notes"])
    check(not has(un["problems"], "TST_Bmany_4x4_A") and any(
        n.startswith("TST_Bmany_4x4_A/TST_Bmany_4x4_A: UV2 charts fill 8%") for n in un["notes"]),
          "under Unity the same UV2 is a box-fill note only: %s" % notes_of(un, "TST_Bmany_4x4_A"))
    check(all("TST_Bmany_4x4_A" in line for line in bk["problems"] if "effective lightmap density" in line),
          "only the many-chart panel is under the gate: %s" % bk["problems"])
    check(not has(probe["problems"], "TST_Bmany_4x4_A/TST_Bmany_4x4_A: effective"),
          "a --probe-lit piece is not lightmapped: no density gate")


@case
def hidden_pieces_measured_as_exported(r):
    rep = r.get("hidden")
    check(len(rep["pieces"]) == 5, [p["piece"] for p in rep["pieces"]])
    for p in rep["pieces"]:
        st = p["objects"][p["piece"]]
        check(st["tris"] == 48 and st["uv2_overlaps"] == 1, "%s measured without its Mirror: %s" % (p["piece"], st))
        check(has(rep["problems"], "%s/%s: 1 pairs of UV2 charts overlap" % (p["piece"], p["piece"])), p["piece"])
    states = r.get("hidden_states")
    check(states["before"] == {"excluded": ["PROP_ArchExcluded_Free_A"], "coll_off": ["PROP_ArchCollOff_Free_A"],
                               "obj_off": ["PROP_ArchObjOff_Free_A"], "eye": ["PROP_ArchHidden_Free_A"]},
          "fixture states %s" % states["before"])
    check(states["after"] == states["before"], "measure() left the visibility changed: %s" % states)
    check(set(states["tris"].values()) == {48}, "live measure(): %s" % states["tris"])


@case
def rename_keeps_placement_ids(r):
    good = r.get("rename_good")
    check(sorted(good["placement_changes"]) == ["stall_%d now places PROP_MarketStall_Free_A (was PROP_Stall_Free_A)"
                                                % n for n in (1, 2, 3)], "a re-point: %s" % good["placement_changes"])
    replaced = r.get("rename_replaced")["placement_changes"]
    check(sorted(replaced) == sorted("stall_%d: id pl-010%d is gone (deleted and placed again, or its id cleared): "
                                     "placement sync would see a new placement" % (n, n) for n in (1, 2, 3)),
          "deleted and placed again under the same names: %s" % replaced)
    renamed = r.get("rename_renamed")["placement_changes"]
    check(sum("vanished" in c for c in renamed) == 3 and sum(" added (" in c for c in renamed) == 3,
          "placed again under new names: %s" % renamed)
    check(has(r.get("rename_replaced")["problems"], "placement stall_1: id pl-0101 is gone"), "no PROBLEM line")


@case
def uv2_layout_scales(r):
    rep, secs = r.get("dense")
    st = piece_of(rep, "TST_Dense_Free_A")["objects"]["TST_Dense_Free_A"]
    check(st["uv2_charts"] == 4608 and st["uv2_overlaps"] == 0 and st["uv2_min_gap_uv"] == 0.004
          and st["uv2_edge_margin_uv"] == 0.102, st)
    check(secs < 60, "4,608 charts took %.0f s: the pair test must stay a sort and sweep" % secs)


@case
def stray_mesh_reported(r):
    rep = r.get("kit")
    check("Stray_Cube" in rep["stray_meshes"] and has(rep["problems"], "stray mesh Stray_Cube"), rep["stray_meshes"])


@case
def per_piece_budget_wins(r):
    probs = r.get("kit")["problems"]
    check(has(probs, "TST_Wall_2x3_A: 12 LOD0 tris > budget 4"), "piece budget not applied")
    check(not has(probs, "TST_Bevel_1x1x1_A", "budget"), "family budget misapplied")


@case
def ngon_under_stale_status(r):
    plain, strict = r.get("kit"), r.get("kit_modelled")
    check(piece_of(plain, "TST_Panel_2x2_A")["objects"]["TST_Panel_2x2_A"]["ngons"] == 1, "n-gon not counted")
    check(not has(plain["problems"], "TST_Panel_2x2_A", "n-gons"), "grey n-gon flagged without --expect-status")
    check(has(strict["problems"], "TST_Panel_2x2_A/TST_Panel_2x2_A: 1 n-gons"), "n-gon hidden by a stale status")
    check(has(strict["problems"], "TST_Panel_2x2_A: kit_status 'grey', expected 'modelled'"), "status mismatch")
    check(not has(strict["problems"], "TST_Wall_2x3_A: kit_status"), "a correct status reported")


@case
def wire_edge_reported(r):
    st = piece_of(r.get("kit"), "TST_Wire_1x1x1_A")["objects"]["TST_Wire_1x1x1_A"]
    check(st["loose_edges"] == 1 and st["loose_verts"] == 0, st)
    check(has(r.get("kit")["problems"], "TST_Wire_1x1x1_A", "wire edges"), "no PROBLEM line for the wire edge")


@case
def coplanar_overlap_reported(r):
    kit = r.get("kit")
    check(piece_of(kit, "TST_Overlap_2x2_A")["coplanar_overlaps"] >= 1, "overlapping quad missed")
    check(has(kit["problems"], "TST_Overlap_2x2_A", "overlapping coplanar faces"), "no PROBLEM line")
    check(piece_of(kit, "TST_Grid_2x2_A")["coplanar_overlaps"] == 0, "adjacent faces counted as overlapping")
    check(piece_of(kit, "TST_Col_1x1x1_A")["coplanar_overlaps"] == 0, "LOD1 counted against LOD0")


@case
def lods_and_collision(r):
    c = piece_of(r.get("kit"), "TST_Col_1x1x1_A")
    check(c["lod0_tris"] == 12 and c["has_collision"], c)


@case
def free_pivots_named(r):
    kit = r.get("kit")
    want = {"TST_Prop_Free_A": "floor_centre", "TST_Lamp_Free_A": "top_centre",
            "TST_Switch_Free_A": "back_face_centre", "TST_Hinge_Free_A": None}
    got = {n: piece_of(kit, n).get("free_pivot") for n in want}
    check(got == want, "free_pivot %s" % got)
    check("pivot_ok" not in piece_of(kit, "TST_Prop_Free_A"), "grid pivot rule applied to a Free piece")


@case
def materials_and_images(r):
    kit, strict = r.get("kit"), r.get("kit_modelled")
    fl = piece_of(kit, "TST_Floor_2x2_A")
    check(fl["bad_materials"] == ["WoodFloor"], fl["bad_materials"])
    check(has(kit["problems"], "TST_Floor_2x2_A: material names not M_<FAMILY>_<Name>: WoodFloor"), "bad name")
    check(has(kit["problems"], "TST_Floor_2x2_A/TST_Floor_2x2_A: empty material slot"), "empty slot")
    check(has(strict["problems"], "TST_Floor_2x2_A: material names"), "names not checked at every stage")
    ims = {i["image"]: i for i in kit["images"]}
    check(ims["T_TST_Gone"]["missing"] and has(kit["problems"], "image T_TST_Gone", "did not load"), ims)
    good = ims["T_TST_Paint_BaseColor.png"]
    check(not good["missing"] and good["size"] == [64, 32], good)


@case
def transform_issue_reported(r):
    kit = r.get("kit")
    m = piece_of(kit, "TST_Moved_1x1x1_A")
    check(m["transform_issues"] == ["TST_Moved_1x1x1_A"] and m["pivot_ok"] is False, m)
    check(has(kit["problems"], "TST_Moved_1x1x1_A: non-identity transforms"), "no PROBLEM line")


@case
def linked_tris_are_evaluated(r):
    kit_tris = piece_of(r.get("kit"), "TST_Bevel_1x1x1_A")["lod0_tris"]
    lp = {p["piece"]: p for p in r.get("master")["linked_pieces"]}
    check(kit_tris > 12, "bevel modifier not evaluated in the KIT (%d tris)" % kit_tris)
    check(lp["TST_Bevel_1x1x1_A"]["tris"] == kit_tris, "linked %s vs KIT %d" % (lp["TST_Bevel_1x1x1_A"], kit_tris))


@case
def asm_file_holds_one_assembly(r):
    rep = r.get("asm")
    check(rep["role"] == "asm" and rep["local_assemblies"] == ["ASM_Booth_A", "ASM_Extra_A"], rep["local_assemblies"])
    check(has(rep["problems"], "ASM_Extra_A: an ASM file holds one assembly"), "second assembly not reported")
    check(not has(rep["problems"], "ASM_Booth_A:") and not has(rep["problems"], "holds no assembly"), rep["problems"])
    check(all(l["relative"] and l["found"] for l in rep["libraries"]), rep["libraries"])
    check(all(p["on_grid"] and p["right_angle"] for p in rep["placements"]), rep["placements"])


@case
def master_copies_reported(r):
    rep, f = r.get("master"), r.f
    check(rep["role"] == "master", rep["role"])
    check("ASM_Copy_A" in rep["appended"] and has(rep["problems"], "ASM_Copy_A is placed from a local copy"),
          rep["appended"])
    check(has(rep["problems"], "ASM_Copy_A: local assembly in MASTER"), "local assembly not reported")
    check(has(rep["problems"], "TST_Slab_2x2_A: local piece collection in a MASTER file"), "local piece missed")
    check(f["shadow_name"] == "TST_Bevel_1x1x1_A", "fixture: Blender renamed the local collection %s"
          % f["shadow_name"])
    check("TST_Bevel_1x1x1_A" in rep["shadowing_linked"] and has(rep["problems"], "shadows a linked one"),
          rep["shadowing_linked"])
    check(rep["ref_meshes"] == ["REF_Figure_1.6m"] and rep["stray_meshes"] == ["Stray_Plane"],
          (rep["ref_meshes"], rep["stray_meshes"]))
    check(rep["unnamed_collections"] == [], rep["unnamed_collections"])


@case
def master_libraries(r):
    libs = {l["path"].replace("\\", "/").split("/")[-1]: l for l in r.get("master")["libraries"]}
    check(libs["KIT_Test.blend"]["relative"] and libs["KIT_Test.blend"]["found"], libs)
    check(libs["ASM_Booth_A.blend"]["relative"] and libs["ASM_Booth_A.blend"]["found"], libs)
    check(not libs["KIT_Abs.blend"]["relative"] and libs["KIT_Abs.blend"]["found"], libs)
    check(has(r.get("master")["problems"], "KIT_Abs.blend is linked by an absolute path"), "absolute path missed")


@case
def master_placements(r):
    rep = r.get("master")
    pl = {p["object"]: p for p in rep["placements"]}
    ok = pl["wall_ok"]
    check(ok["on_grid"] and ok["right_angle"] and ok["rot_xy_ok"] and ok["scale_ok"] and ok["id"] == "id-ok", ok)
    check(not pl["wall_tilt"]["rot_xy_ok"] and has(rep["problems"], "wall_tilt", "tilted"), pl["wall_tilt"])
    check(not pl["wall_scaled"]["scale_ok"] and has(rep["problems"], "wall_scaled", "scaled"), pl["wall_scaled"])
    check(pl["wall_rot45"]["right_angle"] is False and has(rep["problems"], "wall_rot45", "rotated"), pl["wall_rot45"])
    check(pl["wall_offgrid"]["on_grid"] is False and has(rep["problems"], "wall_offgrid", "off grid"),
          pl["wall_offgrid"])
    check(pl["wall_west"]["right_angle"] and not has(rep["problems"], "wall_west"), pl["wall_west"])
    check(pl["booth"]["on_grid"] and pl["booth"]["right_angle"], pl["booth"])
    check(pl["asm_copy"]["on_grid"] is False and pl["asm_copy"]["right_angle"] is False, pl["asm_copy"])
    check(pl["wall_ok"]["kind"] == "grid" and pl["booth"]["kind"] == "asm" and pl["asm_copy"]["kind"] == "asm",
          [(p["object"], p["kind"]) for p in rep["placements"]])
    check(not has(rep["problems"], "placement asm_copy"), "assembly grid data turned into a PROBLEM line")
    check("inner" not in pl, "an instance inside an unplaced collection counted as a placement")


@case
def master_status_behind(r):
    probs = r.get("master_textured")["problems"]
    check(has(probs, "linked piece TST_Wall_2x3_A: kit_status 'modelled' is behind 'textured'"), "behind missed")
    check(not has(probs, "linked piece ABS_Wall_2x3_A"), "a piece at the expected status reported")
    check(not has(r.get("master")["problems"], "is behind"), "status checked without --expect-status")


@case
def placements_compared(r):
    ch = r.get("master_compare")["placement_changes"]
    check(any(c.startswith("wall_ok moved") for c in ch), ch)
    check(any(c.startswith("wall_west added") for c in ch), ch)
    check(any(c.startswith("ghost removed") for c in ch), ch)
    check(len(ch) == 3, ch)


@case
def fbx_reimport(r):
    rep = r.get("fbx")
    check(rep["role"] == "fbx" and [p["piece"] for p in rep["pieces"]] == ["TST_Wall_2x3_A"], rep["pieces"])
    w = rep["pieces"][0]
    ob = next(iter(w["objects"].values()))
    check(not w["transform_issues"] and w["size_ok"] and w["pivot_ok"], w)
    check(w["lod0_tris"] == 12 and ob["uv_layers"] == 2 and ob["materials"] == ["M_TST_Paint"], ob)
    check("Wall" in rep["unnamed_collections"], rep["unnamed_collections"])
    check(not any(s.startswith("Cube") for s in rep["stray_meshes"]), "factory cube left in the session")


@case
def ortho_render_and_overlay(r):
    rep, png = r.get("render_top")
    check(png.exists() and (r.d / "top_overlay.svg").exists(), "render or overlay missing")
    img = bpy.data.images.load(str(png))
    try:
        check(tuple(img.size) == (160, 180), "size %s, want 160 x 180 from the SVG's 10 px/m" % (tuple(img.size),))
    finally:
        bpy.data.images.remove(img)
    st = rep["renders"][0]
    check(st["mean"] is not None and 0 <= st["mean"] <= 255 and st["max"] <= 255, st)
    check("plan.svg" in (r.d / "top_overlay.svg").read_text(encoding="utf-8"), "overlay does not reference the SVG")


@case
def textured_view_render(r):
    rep, png = r.get("render_view")
    check(png.exists() and rep["renders"][0]["mean"] is not None, rep.get("renders"))
    img = bpy.data.images.load(str(png))
    try:
        check(tuple(img.size) == (1280, 720), "size %s" % (tuple(img.size),))
    finally:
        bpy.data.images.remove(img)


@case
def bad_arguments_rejected(r):
    p, _ = run_qa(r.f["master"], ["--render", "top", "--center", "1", "1", "--extent", "2", "2"])
    check(p.returncode != 0 and "needs --png" in (p.stdout + p.stderr), "exit %s: %s"
          % (p.returncode, (p.stdout + p.stderr)[-500:]))


@case
def image_stats_and_gain(r):
    rep = r.get("images")
    check(rep["role"] is None and "pieces" not in rep, "blank session measured a scene")
    st = rep["image_stats"][0]
    check(8 <= st["mean"] <= 12 and st["max"] <= 12, st)
    copy = Path(st["gain_copy"])
    check(copy.exists() and copy.name == "dark_x4.png", st)
    img = bpy.data.images.load(str(copy))
    try:
        px = list(img.pixels[:])
        check(35 <= sum(px[0::4]) / (len(px) / 4) * 255 <= 46, "brightened copy mean")
    finally:
        bpy.data.images.remove(img)


@case
def tile_seam_ratios(r):
    seams = {Path(t["image"]).name: t for t in r.get("images")["tile_seam"]}
    check(seams["seamless.png"]["ratio_x"] <= 1.05, seams["seamless.png"])
    check(seams["seamed.png"]["ratio_x"] > 5, seams["seamed.png"])


@case
def split_task_pieces(r):
    probs = r.get("kit_split")["problems"]
    check(not has(probs, "TST_Panel_2x2_A") and not has(probs, "TST_Floor_2x2_A"), "pieces outside --pieces checked")
    check(not has(probs, "kit_status"), "a status mismatch on a piece the task does not own")
    check(has(probs, "--pieces NOPE_* matches no piece"), "an unmatched --pieces entry passed silently")


@case
def instance_offset_reported(r):
    kit, master = r.get("kit"), r.get("master")
    check(piece_of(kit, "TST_Offset_1x1x1_A")["instance_offset"] == [1.0, 0.0, 0.0], "offset not reported")
    check(has(kit["problems"], "TST_Offset_1x1x1_A: instance_offset [1.0, 0.0, 0.0]"), "no PROBLEM line in the KIT")
    check(has(master["problems"], "linked piece TST_Offset_1x1x1_A: instance_offset"), "no PROBLEM line in MASTER")
    check(not has(kit["problems"], "TST_Wall_2x3_A: instance_offset"), "a zero offset reported")


@case
def trim_on_sub_module(r):
    plain, sub = r.get("master"), r.get("master_sub")
    check(has(plain["problems"], "placement trim (TRIM_Skirting_2_A) off grid"), "trim off the module not reported")
    check(not has(sub["problems"], "placement trim"), "trim on --sub-module still reported")
    check(has(sub["problems"], "placement wall_offgrid"), "--sub-module loosened the grid for other families")


@case
def fbx_shared_texture_no_false_problems(r):
    rep = r.get("fbx_tex")
    check(rep["problems"] == [], "false PROBLEM lines: %s" % rep["problems"])
    mats = {p["piece"]: next(iter(p["objects"].values()))["materials"] for p in rep["pieces"]}
    check(mats == {"TEX_Wall_1x3_A": ["M_TEX_Plaster"], "TEX_Wall_2x3_A": ["M_TEX_Plaster"]}, mats)
    check([f["base"] for f in rep.get("fbx_folded_materials", [])] == ["M_TEX_Plaster"],
          rep.get("fbx_folded_materials"))
    check(rep["images"] and all(i["missing"] for i in rep["images"]), "Strip export images: %s" % rep["images"])


@case
def bad_piece_tris_rejected(r):
    p, _ = run_qa(r.f["kit"], ["--piece-tris", "{INT: 800}"])
    check(p.returncode != 0 and "--piece-tris takes JSON" in (p.stdout + p.stderr),
          "exit %s: %s" % (p.returncode, (p.stdout + p.stderr)[-400:]))


@case
def renders_hide_lods_and_collision(r):
    cov = {k: r.get(k)[0]["renders"][0]["coverage"] for k in ("col_default", "col_show", "col_lod1", "col_hidden")}
    check(0.24 <= cov["col_default"] <= 0.27, "default should draw LOD0 only (0.25 of the frame): %s" % cov)
    check(0.55 <= cov["col_show"] <= 0.58, "--show-collision should draw the 1.5 m shell: %s" % cov)
    check(0.055 <= cov["col_lod1"] <= 0.075, "--lod 1 should draw the 0.5 m LOD1 only: %s" % cov)
    check(cov["col_hidden"] == 0.0, "--hide-object *_LOD0 should leave nothing: %s" % cov)
    master = r.get("master_col")[0]["renders"][0]["coverage"]
    check(0.24 <= master <= 0.27, "linked piece in MASTER drew its collision shell (coverage %s)" % master)


@case
def wire_render(r):
    off, on = r.get("wire_off")[0]["renders"][0], r.get("wire_on")[0]["renders"][0]
    check(off["min"] >= 150, "flat material render should have no dark pixels: %s" % off)
    check(on["min"] <= 60 and on["max"] >= 200, "--wire should draw dark edges on light faces: %s" % on)


@case
def half_module_sizes(r):
    rep = r.get("kit_half")
    ok = {p["piece"]: p.get("size_ok") for p in rep["pieces"]}
    check(ok == {"HLF_Post_1x1x5_A": True, "HLF_Wall_4x1x6_A": False, "HLF_Wall_4x6_A": True},
          "a 0.3 m wall at a 0.5 m module is 4x6 and a 0.5 m post 1x1x5: %s" % ok)


@case
def module_required(r):
    p, _ = run_qa(r.f["kit"], ["--expect-status", "modelled"], module=False)
    check(p.returncode != 0 and "--module is required" in (p.stdout + p.stderr),
          "a KIT run without --module ran: exit %s" % p.returncode)
    p, _ = run_qa(None, ["--image-stats", r.f["dark"]], module=False)
    check(p.returncode == 0, "a blank-session image run should not need --module: %s" % (p.stdout + p.stderr)[-300:])


@case
def uv2_layout_measured(r):
    kit, probe = r.get("kit"), r.get("kit_probe")
    gap = piece_of(kit, "TST_Gap_2x2_A")["objects"]["TST_Gap_2x2_A"]
    check(gap["uv2_charts"] == 2 and gap["uv2_overlaps"] == 0 and abs(gap["uv2_min_gap_uv"] - 0.01) < 1e-4, gap)
    check(gap["uv2_min_gap_texels"] < 2 and has(kit["problems"], "TST_Gap_2x2_A/TST_Gap_2x2_A: UV2 charts"),
          "a 0.01 UV gap at a ~44 px footprint passed: %s" % gap)
    lap = piece_of(kit, "TST_Lap_2x2_A")["objects"]["TST_Lap_2x2_A"]
    check(lap["uv2_overlaps"] == 1 and has(kit["problems"], "TST_Lap_2x2_A/TST_Lap_2x2_A: 1 pairs of UV2 charts overlap"),
          lap)
    check(not has(kit["problems"], "TST_Good_2x2_A"), "the good layout was flagged")
    check(has(kit["problems"], "TST_Floor_2x2_A/TST_Floor_2x2_A: no UV2"), "a textured mesh without UV2 passed")
    check(not has(probe["problems"], "TST_Lap_2x2_A") and has(probe["problems"], "TST_Gap_2x2_A"),
          "--probe-lit should skip only the named piece's UV2 layout")


@case
def texture_renders_use_the_render_uv(r):
    default, uv2 = r.get("uv_default")[0]["renders"][0], r.get("uv_uv2")[0]["renders"][0]
    check(100 <= default["mean"] <= 155, "default should draw UV0 (half black, half white): %s" % default)
    check(uv2["mean"] >= 240, "--uv-layer UV2 should draw the white half only: %s" % uv2)


@case
def sealed_inner_shell(r):
    kit = r.get("kit")
    check(piece_of(kit, "TST_Hidden_1x1x1_A")["objects"]["TST_Hidden_1x1x1_A"]["islands"] == 2
          and piece_of(kit, "TST_Solid_1x1x1_A")["objects"]["TST_Solid_1x1x1_A"]["islands"] == 1, "islands")
    solid, hidden = r.get("section_solid")[0]["renders"][0], r.get("section_hidden")[0]["renders"][0]
    check(hidden["mean"] < solid["mean"] - 5, "the section should show the inner shell's edges: %s vs %s"
          % (hidden, solid))


@case
def linked_assembly_offset(r):
    master = r.get("master")
    check(master["linked_assembly_offsets"].get("ASM_Shift_A") == [0.5, 0.0, 0.0], master["linked_assembly_offsets"])
    check(has(master["problems"], "linked assembly ASM_Shift_A: instance_offset [0.5, 0.0, 0.0]"), "no PROBLEM line")
    check(not has(master["problems"], "linked assembly ASM_Booth_A"), "a zero offset reported")


def main():
    d = Path(tempfile.mkdtemp(prefix="qa_measure_fixtures_"))
    failed = []
    try:
        try:
            f = build(d)
        except Exception:
            traceback.print_exc()
            raise RuntimeError("fixture build failed")
        runs = Runs(d, f)
        for fn in CASES:
            try:
                fn(runs)
                print("PASS %s" % fn.__name__)
            except Exception as exc:
                failed.append(fn.__name__)
                print("FAIL %s: %s" % (fn.__name__, exc))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("%d case(s), %d failed" % (len(CASES), len(failed)))
    if failed:
        raise RuntimeError("failed: " + ", ".join(failed))


main()
