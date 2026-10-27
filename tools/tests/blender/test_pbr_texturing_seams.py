"""Blender-hosted tests for the pbr-texturing skill's scripts/texture_seams.py (shipped identically in vrchat-world-qa):
seams that show and seams that do not, on colour bakes, a normal bake, a normal map whose island moved after the
bake, and the joints of kit pieces placed as collection instances.

Host: Blender 5.2.2 (4.2+), headless, Cycles on the CPU. Builds its fixtures in memory and a temp folder, prints
PASS <case> / FAIL <case>: <why> per case and raises when any case failed:
    blender -b --factory-startup --python-exit-code 1 --python tools/tests/blender/test_pbr_texturing_seams.py
"""

import math
import os
import sys
import tempfile
import traceback
from pathlib import Path

import bmesh
import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "skills" / "pbr-texturing" / "scripts" / "texture_seams.py"
NS = {"TEXTURE_SEAMS_NO_MAIN": True, "__name__": "texture_seams_under_test"}
exec(compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec"), NS)
TMP = tempfile.mkdtemp()


def check(cond, why):
    if not cond:
        raise AssertionError(why)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 4
    sc.cycles.device = "CPU"


def select_only(*obs):
    for o in bpy.context.scene.objects:
        o.select_set(o in obs)
    bpy.context.view_layer.objects.active = obs[0]


def sphere_low():
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=1.0)
    low = bpy.context.active_object
    low.name = "LOW"
    bpy.ops.object.shade_smooth()
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.03)
    bpy.ops.object.mode_set(mode="OBJECT")
    low.modifiers.new("Tri", "TRIANGULATE")
    bpy.ops.object.modifier_apply(modifier="Tri")
    return low


def image_node(ob, name, size=512, float_buffer=False):
    mat = bpy.data.materials.new("M_" + name)
    mat.use_nodes = True
    img = bpy.data.images.new("I_" + name, size, size, float_buffer=float_buffer)
    img.colorspace_settings.name = "Non-Color"
    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = img
    mat.node_tree.nodes.active = node
    ob.data.materials.clear()
    ob.data.materials.append(mat)
    return mat, img


def save(img, name):
    p = os.path.join(TMP, name)
    img.filepath_raw = p
    img.file_format = "PNG"
    img.save()
    return p


def bake_noise(low, coord):
    mat, img = image_node(low, coord)
    nt = mat.node_tree
    out = nt.nodes.get("Material Output") or nt.nodes.new("ShaderNodeOutputMaterial")
    em, tc, nz = (nt.nodes.new(t) for t in ("ShaderNodeEmission", "ShaderNodeTexCoord", "ShaderNodeTexNoise"))
    nz.inputs["Scale"].default_value = 4.0
    nt.links.new(tc.outputs[coord], nz.inputs["Vector"])
    nt.links.new(nz.outputs["Color"], em.inputs["Color"])
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    select_only(low)
    sc = bpy.context.scene
    sc.render.bake.use_selected_to_active = False
    sc.render.bake.margin = 16
    bpy.ops.object.bake(type="EMIT")
    return save(img, "T_%s.png" % coord)


# ----------------------------------------------------------------------------------------------- cases
def noise_from_uv_shows_from_object_does_not():
    low = sphere_low()
    bad = NS["seams"](low, bake_noise(low, "UV"))
    good = NS["seams"](low, bake_noise(low, "Object"))
    check(bad["visible_m"] > 0.9 * bad["seam_m"] and bad["ratio_p50"] > 4, "UV-space noise: %s" % bad)
    check(good["visible_m"] == 0 and good["ratio_p95"] < 1.6 and not good["issues"], "object-space noise: %s" % good)


def normal_bake_clean_until_an_island_moves():
    low = sphere_low()
    bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=48, radius=1.0)
    high = bpy.context.active_object
    bpy.ops.object.shade_smooth()
    tex = bpy.data.textures.new("bumps", "VORONOI")
    tex.noise_scale = 0.3
    dm = high.modifiers.new("D", "DISPLACE")
    dm.texture, dm.strength, dm.texture_coords = tex, 0.03, "OBJECT"
    _mat, img = image_node(low, "N", float_buffer=True)
    select_only(low, high)
    sc = bpy.context.scene
    sc.render.bake.use_selected_to_active = True
    sc.render.bake.cage_extrusion = 0.08
    sc.render.bake.margin = 16
    bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT")
    path = save(img, "T_N.png")
    r = NS["seams"](low, path, kind="normal")
    check(r["visible_m"] == 0 and r["edges"] > 50, "a clean MikkTSpace bake should show no seam: %s" % r)
    # turn the island of face 0 by 90 deg after the bake: the tangent basis no longer matches the map
    me = low.data
    bm = bmesh.new()
    bm.from_mesh(me)
    uvk = bm.loops.layers.uv.active
    bm.faces.ensure_lookup_table()
    island, todo = {0}, [bm.faces[0]]
    while todo:
        f = todo.pop()
        for lp in f.loops:
            for g in lp.edge.link_faces:
                if g.index in island:
                    continue
                same = all((next(x for x in f.loops if x.vert == v)[uvk].uv
                            - next(x for x in g.loops if x.vert == v)[uvk].uv).length < 1e-6 for v in lp.edge.verts)
                if same:
                    island.add(g.index)
                    todo.append(g)
    corners = [lp for i in island for lp in bm.faces[i].loops]
    cu = sum(lp[uvk].uv.x for lp in corners) / len(corners)
    cv = sum(lp[uvk].uv.y for lp in corners) / len(corners)
    for lp in corners:
        du, dv = lp[uvk].uv.x - cu, lp[uvk].uv.y - cv
        lp[uvk].uv = (cu - dv, cv + du)
    bm.to_mesh(me)
    bm.free()
    r = NS["seams"](low, path, kind="normal")
    check(r["visible_m"] > 1.0 and r["issues"], "a turned island must show at its border: %s" % r)


def hard_edges_crease_is_not_a_seam():
    """Arch sweep FP 2: a chamfered box with hard edges (and a UV seam on each, as uv-unwrapping requires) under a flat
    normal map: its shading creases at every chamfer are the mesh's, so no seam shows; one face's island painted 20
    deg off still shows along its border."""
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    ob = bpy.context.active_object
    bev = ob.modifiers.new("Bevel", "BEVEL")
    bev.width, bev.segments = 0.08, 1
    bpy.ops.object.modifier_apply(modifier="Bevel")
    ob.data.set_sharp_from_angle(angle=math.radians(30))
    ob.data.shade_smooth()
    select_only(ob)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(30), island_margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")
    ob.modifiers.new("Tri", "TRIANGULATE")
    n = 512
    px = np.tile(np.array([0.5, 0.5, 1.0, 1.0], np.float32), (n, n, 1))
    img = bpy.data.images.new("flat_n", n, n)
    img.colorspace_settings.name = "Non-Color"
    img.pixels.foreach_set(px.ravel())
    r = NS["seams"](ob, save(img, "T_flat_Normal.png"), kind="normal")
    check(r["seam_m"] > 1 and r["visible_m"] == 0, "flat map on hard edges: %s" % r)
    me = ob.data                                               # the biggest face's island, tilted 20 deg about V
    big = max(me.polygons, key=lambda p: p.area)
    uv = np.array([me.uv_layers.active.data[li].uv[:] for li in big.loop_indices])
    (x0, y0), (x1, y1) = np.floor(uv.min(0) * n).astype(int) - 3, np.ceil(uv.max(0) * n).astype(int) + 3
    tilt = math.radians(20)
    px[max(y0, 0):y1, max(x0, 0):x1, :3] = (0.5 + 0.5 * math.sin(tilt), 0.5, 0.5 + 0.5 * math.cos(tilt))
    img.pixels.foreach_set(px.ravel())
    r = NS["seams"](ob, save(img, "T_tilt_Normal.png"), kind="normal")
    check(r["visible_m"] > 1.0, "a tilted island must show at its border: %s" % r)


def brick_tile(n=256, seed=4):
    """A seamless 1 m brick tile: four courses, half-bond, a tone per brick, mortar lines."""
    rng = np.random.default_rng(seed)
    img = np.ones((n, n, 4), np.float32)
    course = n // 4
    for r in range(4):
        off = (n // 4) if r % 2 else 0
        for b in range(2):
            x0 = (off + b * n // 2) % n
            tone = rng.uniform(0.35, 0.75)
            xs = (np.arange(n // 2) + x0) % n
            img[r * course:(r + 1) * course, xs, 0] = tone
            img[r * course:(r + 1) * course, xs, 1] = tone * 0.55
            img[r * course:(r + 1) * course, xs, 2] = tone * 0.45
            img[r * course:r * course + 4, xs, :3] = 0.8                      # bed joint
            img[r * course:(r + 1) * course, x0:x0 + 4, :3] = 0.8             # head joint
    return img


def wall_piece(name, length, height=3.0, thick=0.3):
    me = bpy.data.meshes.new(name)
    v = [(x, y, z) for z in (0, height) for y in (0, thick) for x in (0, length)]
    f = [(0, 1, 5, 4), (3, 2, 6, 7), (2, 0, 4, 6), (1, 3, 7, 5), (4, 5, 7, 6), (2, 3, 1, 0)]
    me.from_pydata(v, [], f)
    me.update()
    lay = me.uv_layers.new(name="UVMap")
    for p in me.polygons:                                  # front (-Y) and back (+Y): U from x at 1 m, V from z
        for li in range(p.loop_start, p.loop_start + p.loop_total):
            co = me.vertices[me.loops[li].vertex_index].co
            n = p.normal
            ax = max(range(3), key=lambda k: abs(n[k]))
            s = 1.0 if n[ax] >= 0 else -1.0
            u, vv = ((s * co.y, co.z) if ax == 0 else (-s * co.x, co.z) if ax == 1 else (s * co.x, co.y))
            lay.data[li].uv = (u, vv)
    return bpy.data.objects.new(name, me)


def kit_joints_through_collection_instances():
    path = os.path.join(TMP, "T_EXT_Brick_BaseColor.png")
    img = bpy.data.images.new("brick", 256, 256)
    img.pixels.foreach_set(brick_tile().ravel())
    img.filepath_raw, img.file_format = path, "PNG"
    img.save()
    pieces = {}
    for name, length in (("WALL_1m", 1.0), ("WALL_2m", 2.0)):
        col = bpy.data.collections.new("KIT_" + name)
        bpy.context.scene.collection.children.link(col)
        ob = wall_piece(name, length)
        col.objects.link(ob)
        pieces[name] = (col, ob)
    bpy.context.view_layer.layer_collection.children["KIT_WALL_1m"].exclude = True
    bpy.context.view_layer.layer_collection.children["KIT_WALL_2m"].exclude = True
    placed = []
    for i, (name, x) in enumerate((("WALL_1m", 0.0), ("WALL_2m", 1.0), ("WALL_1m", 3.0))):
        e = bpy.data.objects.new("P%d_%s" % (i, name), None)
        e.instance_type, e.instance_collection, e.location = "COLLECTION", pieces[name][0], (x, 0, 0)
        bpy.context.scene.collection.objects.link(e)
        placed.append(e)
    bpy.context.view_layer.update()
    r = NS["joints"](placed, path)
    check(len(r["pairs"]) == 2 and r["visible_m"] == 0 and r["seam_m"] > 5, "phase-0 pieces: %s" % r)
    jp = os.path.join(TMP, "joints.json")                # the CLI on the whole file: the kit masters (excluded
    code = NS["_run"](["--objects", "*", "--image", path, "--joints", "--json", jp])   # collections) are left out
    rep = __import__("json").load(open(jp, encoding="utf-8"))[0]
    check(code == 0 and rep["pieces"] == 3 and len(rep["pairs"]) == 2, "CLI joints: exit %s, %s" % (code, rep))
    # Cube Projection on the 2 m piece centres it on its bounds: half a tile off at both of its joints
    ob = pieces["WALL_2m"][1]
    bpy.context.view_layer.layer_collection.children["KIT_WALL_2m"].exclude = False
    select_only(ob)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.cube_project(cube_size=1.0, correct_aspect=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.layer_collection.children["KIT_WALL_2m"].exclude = True
    bpy.context.view_layer.update()
    r = NS["joints"](placed, path)
    check(r["visible_m"] > 5 and r["issues"], "cube-projected 2 m piece must show at its joints: %s" % r)



def mirrored_piece_joins_its_neighbour():
    """A piece placed with a negative scale has its faces' winding reversed in world space; its joint with an
    unmirrored neighbour is still a joint (the faces face the same way), so it is paired and checked."""
    path = os.path.join(TMP, "T_EXT_Brick_BaseColor.png")
    img = bpy.data.images.new("brick", 256, 256)
    img.pixels.foreach_set(brick_tile().ravel())
    img.filepath_raw, img.file_format = path, "PNG"
    img.save()
    col = bpy.data.collections.new("KIT_WALL_1m")
    bpy.context.scene.collection.children.link(col)
    col.objects.link(wall_piece("WALL_1m", 1.0))
    bpy.context.view_layer.layer_collection.children["KIT_WALL_1m"].exclude = True
    placed = []
    for name, x, sx in (("P0", 0.0, 1.0), ("P1_mirrored", 2.0, -1.0)):           # P1 covers x 1-2, mirrored
        e = bpy.data.objects.new(name, None)
        e.instance_type, e.instance_collection = "COLLECTION", col
        e.location, e.scale = (x, 0, 0), (sx, 1, 1)
        bpy.context.scene.collection.objects.link(e)
        placed.append(e)
    bpy.context.view_layer.update()
    r = NS["joints"](placed, path)
    check(len(r["pairs"]) == 1 and r["seam_m"] > 5, "the mirrored piece's joint must be paired: %s" % r)


def front_object(name, polys, du=0.0, material=None, other=None):
    """A mesh of faces in the y = 0 plane facing -Y, U = x + du and V = z (a 1 m tile); polys: lists of (x, z)
    corners counter-clockwise seen from -Y. other: (polygon, material name) faces on a second material."""
    me = bpy.data.meshes.new(name)
    verts, faces, idx = [], [], {}
    for poly in polys + ([other[0]] if other else []):
        f = []
        for x, z in poly:
            if (x, z) not in idx:
                idx[(x, z)] = len(verts)
                verts.append((x, 0.0, z))
            f.append(idx[(x, z)])
        faces.append(f)
    me.from_pydata(verts, [], faces)
    me.update()
    lay = me.uv_layers.new(name="UVMap")
    for p in me.polygons:
        for li in range(p.loop_start, p.loop_start + p.loop_total):
            co = me.vertices[me.loops[li].vertex_index].co
            lay.data[li].uv = (co.x + du, co.z)
    for m in (material, other[1] if other else None):
        if m:
            me.materials.append(bpy.data.materials.get(m) or bpy.data.materials.new(m))
    if other:
        me.polygons[-1].material_index = 1
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def joints_long_triangles_and_partial_edges():
    """A joint whose faces are long triangles (a fan-triangulated spandrel: their centroids lie far along the joint
    edge) is judged, so a 0.3-tile jump shows; edges that only partly coincide give a NOTE, not a silent pass; and the
    normal-map check judges one material of a piece whose n-gons all lie on another."""
    path = os.path.join(TMP, "T_EXT_Brick_BaseColor.png")
    img = bpy.data.images.new("brick", 256, 256)
    img.pixels.foreach_set(brick_tile().ravel())
    img.filepath_raw, img.file_format = path, "PNG"
    img.save()
    left = [[(1.9, 3.0), (2.0, 0.0), (2.0, 0.3)][::-1], [(1.0, 0.0), (2.0, 0.0), (1.9, 3.0)]]
    right = [[(2.0, 0.0), (2.1, 3.0), (2.0, 0.3)][::-1], [(2.0, 0.0), (3.0, 0.0), (2.1, 3.0)]]
    a = front_object("A_fan", left)
    b = front_object("B_fan", right)
    bpy.context.view_layer.update()
    r = NS["joints"]([a, b], path)
    check(r["edges"] >= 1 and r["visible_m"] == 0, "long triangles at a continuing joint: %s" % r)
    bpy.data.objects.remove(b)
    b = front_object("B_shifted", right, du=0.3)
    bpy.context.view_layer.update()
    r = NS["joints"]([a, b], path)
    check(r["visible_m"] > 0 and r["issues"], "a 0.3-tile jump between long triangles must show: %s" % r)
    tall = front_object("C_tall", [[(0.0, 0.0), (2.0, 0.0), (2.0, 4.0), (0.0, 4.0)]])
    short = front_object("D_short", [[(2.0, 0.0), (4.0, 0.0), (4.0, 2.0), (2.0, 2.0)]])
    bpy.context.view_layer.update()
    r = NS["joints"]([tall, short], path)
    check(r["t_junctions"] and any("inside an edge" in n for n in r["notes"]), "a T-junction joint: %s" % r)
    ngon = [(5.0, 2.0), (5.5, 2.0), (6.0, 2.2), (5.7, 2.8), (5.2, 2.6)]
    mixed = front_object("E_mixed", [[(4.0, 0.0), (6.0, 0.0), (6.0, 2.0), (4.0, 2.0)]], material="M_EXT_Brick",
                         other=(ngon, "M_EXT_Stone"))
    bpy.context.view_layer.update()
    r = NS["joints"]([short, mixed], path, kind="normal", material="M_EXT_Brick")
    check("edges" in r, "an n-gon outside the judged material must not stop the normal check: %s" % r)
    try:
        NS["joints"]([short, mixed], path, kind="normal", material="M_EXT_Stone")
        raise AssertionError("an n-gon inside the judged material must be refused")
    except ValueError:
        pass

def maths_without_meshes():
    img = np.zeros((4, 4, 3))
    img[:, 0] = 1.0                                        # column 0 bright: wraps onto column 3's right edge
    s = NS["sample"](img, [(0.0, 0.5), (1.0, 0.5), (0.125, 0.5)])
    check(np.allclose(s[0], 0.5) and np.allclose(s[1], 0.5) and np.allclose(s[2], 1.0), s)
    step = NS["inward"]((0, 0), (1, 0), (0.5, 0.5), (4, 4))
    check(np.allclose(step, (0, 0.25)), step)
    up = NS["shade"]([(0.5, 0.5, 1.0)], [(1, 0, 0)], [1.0], [(0, 0, 1)])
    check(np.allclose(up, (0, 0, 1)), up)
    tilted = NS["shade"]([(0.5, 1.0, 0.5)], [(1, 0, 0)], [1.0], [(0, 0, 1)])
    check(np.allclose(tilted, (0, 1, 0)), "green up = +bitangent = normal x tangent: %s" % tilted)
    check(NS["verdict"]([0.1], [0.01], "color") == (10.0, True, True), "a tenfold step shows")
    check(NS["verdict"]([0.025], [0.01], "color")[1:] == (False, True), "two and a half times: a look, not an issue")
    check(NS["verdict"]([0.005], [0.001], "color")[1:] == (False, False), "under the floor it does not")
    check(NS["verdict"]([0.1], [0.01], "color", base=0.05)[1] is False, "a busy texture's baseline lifts the bar")
    check(NS["baseline"](np.dstack([np.tile([0.0, 1.0], (4, 2))] * 3), "color") > 0.4, "a checker's baseline")


CASES = [maths_without_meshes, noise_from_uv_shows_from_object_does_not, normal_bake_clean_until_an_island_moves,
         kit_joints_through_collection_instances, mirrored_piece_joins_its_neighbour,
         joints_long_triangles_and_partial_edges, hard_edges_crease_is_not_a_seam]


def main():
    print("texture_seams Blender tests on Blender %s" % bpy.app.version_string)
    failed = []
    for case in CASES:
        reset()
        try:
            case()
            print("PASS %s" % case.__name__)
        except Exception as e:                                 # report every case, then fail the run
            print("FAIL %s: %s" % (case.__name__, e))
            traceback.print_exc()
            failed.append(case.__name__)
    print("%d case(s), %d failed" % (len(CASES), len(failed)))
    if failed:
        raise RuntimeError("failed: " + ", ".join(failed))


main()
