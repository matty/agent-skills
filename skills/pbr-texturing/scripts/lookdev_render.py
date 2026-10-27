"""Look-dev renders: exported maps, a material or objects rendered with EEVEE (or Cycles) under a CC0 HDRI that ships
with Blender (datafiles/studiolights/world, from Poly Haven), Standard view transform, so base colour, roughness,
metallic and normal maps read the way a PBR engine shows them. Workbench shows none of the last three: judge
materials here, not in a Workbench render.

Host: Blender 4.2+ (bpy), no add-ons; tested on Blender 5.2.2. Adds a temporary camera, world and preview meshes and
removes them; render settings are restored after the render; never saves.

Command line:
    blender -b --factory-startup --python-exit-code 1 --python lookdev_render.py --
            --maps "blender/textures/EXT/T_EXT_Brick_*.png" --png brick.png       # the maps on a sphere and a cube
    blender -b --factory-startup KIT_Arch_Exterior.blend --python-exit-code 1 --python lookdev_render.py --
            --object EXT_Wall_2x3_A --png wall.png [--hdri courtyard] [--size 1280 720] [--engine cycles]
    blender -b --factory-startup chest_bake.blend --python-exit-code 1 --python lookdev_render.py --
            --object Chest_low --maps "textures/T_PROP_Chest_*.png" --eye 0 -0.5 1.1 --target 0 0 0.4 --png held.png
            (the exported maps on the object, in place of its own material such as a bake's, seen from the player's
            eye: a pickup held at 0.5 m, a wall from 1.6 m up at its usual distance)
As a module (Blender MCP or another script):
    ns = {"LOOKDEV_NO_MAIN": True}; exec(open(path, encoding="utf-8").read(), ns)
    mat = ns["material_from_maps"]("M_EXT_Brick", base_color=..., metallic_smoothness=..., normal=...)
    ns["render"](objects, "brick.png")
HDRIs: city, courtyard, forest, interior, night, studio (default), sunrise, sunset, or a path to any .exr / .hdr.
"""

import argparse
import glob
import math
import os
import sys

import bpy
from mathutils import Vector

HDRI_DIR = bpy.utils.system_resource("DATAFILES", path="studiolights/world")
ROLE_SUFFIX = {"basecolor": "base_color", "albedo": "base_color", "albedotransparency": "base_color",
               "metallicsmoothness": "metallic_smoothness", "normal": "normal"}


def _image(path, colour):
    img = bpy.data.images.load(os.path.abspath(path), check_existing=True)
    img.colorspace_settings.name = "sRGB" if colour else "Non-Color"
    if not colour:
        # data in every channel; measured on Blender 5.2.2: a Non-Color image keeps RGB under alpha 0 in any alpha
        # mode, so this states the intent rather than fixing a loss
        img.alpha_mode = "CHANNEL_PACKED"
    return img


def material_from_maps(name, base_color=None, metallic_smoothness=None, normal=None, tiling=1.0):
    """A Principled BSDF material wired the way the exported maps mean it: base colour sRGB; the packed map Non-Color,
    metallic from R and roughness = 1 - A (Unity's smoothness); the normal map Non-Color through a tangent-space Normal
    Map node (OpenGL Y+, as Blender bakes). tiling repeats the maps (a tiling material on a preview mesh)."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (tiling, tiling, tiling)
    nt.links.new(coord.outputs["UV"], mapping.inputs["Vector"])

    def tex(path, colour):
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = _image(path, colour)
        nt.links.new(mapping.outputs["Vector"], node.inputs["Vector"])
        return node

    if base_color:
        nt.links.new(tex(base_color, True).outputs["Color"], bsdf.inputs["Base Color"])
    if metallic_smoothness:
        ms = tex(metallic_smoothness, False)
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(ms.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Red"], bsdf.inputs["Metallic"])
        inv = nt.nodes.new("ShaderNodeMath")
        inv.operation = "SUBTRACT"
        inv.inputs[0].default_value = 1.0
        nt.links.new(ms.outputs["Alpha"], inv.inputs[1])
        nt.links.new(inv.outputs["Value"], bsdf.inputs["Roughness"])
    if normal:
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.space = "TANGENT"
        nt.links.new(tex(normal, False).outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def maps_by_role(paths):
    """{"base_color": path, "metallic_smoothness": path, "normal": path} from T_<FAMILY>_<Name>_<Map>.png names."""
    out = {}
    for p in paths:
        suffix = os.path.splitext(os.path.basename(p))[0].rsplit("_", 1)[-1].lower()
        if suffix in ROLE_SUFFIX:
            out[ROLE_SUFFIX[suffix]] = p
    return out


def preview_meshes(mat):
    """A UV sphere and a cube side by side, smooth-shaded where curved, both carrying mat; returns the two objects."""
    made = []
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, location=(-0.65, 0, 0.5), segments=64, ring_count=32)
    sphere = bpy.context.active_object
    for p in sphere.data.polygons:
        p.use_smooth = True
    made.append(sphere)
    bpy.ops.mesh.primitive_cube_add(size=0.9, location=(0.65, 0, 0.45), rotation=(0, 0, math.radians(30)))
    made.append(bpy.context.active_object)
    for ob in made:
        ob.data.materials.append(mat)
    return made


def _bounds(objects):
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for ob in objects:
        ev = ob.evaluated_get(dg)
        pts += [ev.matrix_world @ Vector(c) for c in ev.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def _set_engine(scene, engine):
    names = ["CYCLES"] if engine == "cycles" else ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"]
    for n in names:
        try:
            scene.render.engine = n
            return n
        except TypeError:
            continue
    raise RuntimeError("no EEVEE or Cycles engine available")


def render(objects, png, size=(960, 540), hdri="studio", strength=1.0, engine="eevee", samples=32,
           view=(1.0, -1.6, 0.9), lens=50.0, eye=None, target=None):
    """Render objects (a list) to png from a three-quarter view that frames their bounds (view: the camera direction
    from their centre, in units of their size), or from eye (world metres) looking at target (default their centre),
    lit only by the HDRI (a name from Blender's studiolights/world or a file path) at the given strength, Standard
    view transform, no look, exposure 0. Returns the engine used."""
    scene = bpy.context.scene
    hdri_path = hdri if os.path.isfile(str(hdri)) else os.path.join(HDRI_DIR, "%s.exr" % hdri)
    if not os.path.isfile(hdri_path):
        raise ValueError("no HDRI %r (Blender ships %s)" % (hdri, ", ".join(
            sorted(os.path.splitext(f)[0] for f in os.listdir(HDRI_DIR) if f.endswith(".exr")))))
    keep = dict(engine=scene.render.engine, camera=scene.camera, world=scene.world, x=scene.render.resolution_x,
                y=scene.render.resolution_y, pct=scene.render.resolution_percentage, path=scene.render.filepath,
                fmt=scene.render.image_settings.file_format, view=scene.view_settings.view_transform,
                look=scene.view_settings.look, exposure=scene.view_settings.exposure,
                gamma=scene.view_settings.gamma, film=scene.render.film_transparent)
    hidden = [ob for ob in scene.objects if ob.type in ("MESH", "CURVE", "LIGHT") and ob not in objects
              and not ob.hide_render]
    temp_objs, temp_data = [], []
    try:
        for ob in hidden:
            ob.hide_render = True
        world = bpy.data.worlds.new("lookdev_world")
        temp_data.append(world)
        world.use_nodes = True
        nt = world.node_tree
        bg = next(n for n in nt.nodes if n.type == "BACKGROUND")
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(hdri_path, check_existing=True)
        nt.links.new(env.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = strength
        scene.world = world
        lo, hi = _bounds(objects)
        centre, extent = (lo + hi) / 2, max((hi - lo).length, 1e-3)
        cam_data = bpy.data.cameras.new("lookdev_cam")
        cam_data.lens = lens
        temp_data.append(cam_data)
        cam = bpy.data.objects.new("lookdev_cam", cam_data)
        temp_objs.append(cam)
        scene.collection.objects.link(cam)
        d = Vector(view).normalized()
        sensor_half = cam_data.sensor_width / 2.0
        dist = (extent / 2.0) / (sensor_half / lens) * 1.15 * max(1.0, size[1] / float(size[0]) * 16 / 9)
        cam.location = centre + d * dist
        cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
        if eye is not None:                         # the player's eye: a pickup held at 0.5 m, a wall at its distance
            cam.location = Vector(eye)
            aim = Vector(target) if target is not None else centre
            cam.rotation_euler = (aim - Vector(eye)).to_track_quat("-Z", "Y").to_euler()
            cam_data.clip_start = 0.01
        scene.camera = cam
        used = _set_engine(scene, engine)
        if used == "CYCLES":
            scene.cycles.samples = samples
        elif hasattr(scene, "eevee"):
            scene.eevee.taa_render_samples = samples
        scene.render.resolution_x, scene.render.resolution_y = size
        scene.render.resolution_percentage = 100
        scene.render.film_transparent = False
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
        scene.view_settings.exposure = 0.0
        scene.view_settings.gamma = 1.0
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = os.path.abspath(png)
        bpy.ops.render.render(write_still=True)
        return used
    finally:
        for ob in hidden:
            ob.hide_render = False
        for ob in temp_objs:
            bpy.data.objects.remove(ob)
        scene.world = keep["world"]
        scene.camera = keep["camera"]
        for block in temp_data:
            if isinstance(block, bpy.types.World):
                bpy.data.worlds.remove(block)
            elif isinstance(block, bpy.types.Camera):
                bpy.data.cameras.remove(block)
        scene.render.engine = keep["engine"]
        scene.render.resolution_x, scene.render.resolution_y = keep["x"], keep["y"]
        scene.render.resolution_percentage = keep["pct"]
        scene.render.filepath = keep["path"]
        scene.render.image_settings.file_format = keep["fmt"]
        scene.view_settings.view_transform = keep["view"]
        scene.view_settings.look = keep["look"]
        scene.view_settings.exposure = keep["exposure"]
        scene.view_settings.gamma = keep["gamma"]
        scene.render.film_transparent = keep["film"]


def main(argv):
    ap = argparse.ArgumentParser(prog="lookdev_render.py", description=__doc__.split("\n")[0])
    ap.add_argument("--maps", help="maps or a quoted glob: T_<FAMILY>_<Name>_BaseColor/MetallicSmoothness/Normal.png "
                    "(alone: on a sphere and a cube; with --object: on those objects in place of their materials)")
    ap.add_argument("--object", action="append", help="an object in the open .blend (repeat for several)")
    ap.add_argument("--eye", type=float, nargs=3, metavar=("X", "Y", "Z"), help="camera position in metres (the "
                    "player's eye) instead of the framed three-quarter view")
    ap.add_argument("--target", type=float, nargs=3, metavar=("X", "Y", "Z"), help="with --eye: where it looks "
                    "(default the objects' centre)")
    ap.add_argument("--lens", type=float, default=50.0, help="focal length in mm (36 mm sensor; 24 for a wide view)")
    ap.add_argument("--png", required=True)
    ap.add_argument("--hdri", default="studio")
    ap.add_argument("--strength", type=float, default=1.0)
    ap.add_argument("--size", type=int, nargs=2, default=(960, 540))
    ap.add_argument("--engine", choices=("eevee", "cycles"), default="eevee")
    ap.add_argument("--samples", type=int, default=32)
    ap.add_argument("--tiling", type=float, default=1.0, help="with --maps: repeats per UV unit on the preview meshes")
    a = ap.parse_args(argv)
    if not (a.maps or a.object):
        ap.error("give --maps, --object, or both")
    made, mat, swapped = [], None, []
    try:
        if a.maps:
            roles = maps_by_role(sorted(glob.glob(a.maps)) or [a.maps])
            if not roles:
                print("[lookdev] no map matched %s" % a.maps)
                return 2
            mat = material_from_maps("lookdev_material", tiling=a.tiling, **roles)
        if a.object:
            missing = [n for n in a.object if n not in bpy.data.objects]
            if missing:
                print("[lookdev] no object named %s" % ", ".join(missing))
                return 2
            objects = [bpy.data.objects[n] for n in a.object]
            for ob in objects if mat is not None else ():      # the maps in place of each slot's material
                if not ob.material_slots:
                    ob.data.materials.append(mat)
                    swapped.append((ob, None, None))
                for i, slot in enumerate(ob.material_slots):
                    if slot.material is not mat:
                        swapped.append((ob, i, slot.material))
                        slot.material = mat
        else:
            objects = made = preview_meshes(mat)
        used = render(objects, a.png, size=tuple(a.size), hdri=a.hdri, strength=a.strength, engine=a.engine,
                      samples=a.samples, lens=a.lens, eye=a.eye, target=a.target)
        print("[lookdev] %s -> %s (%s, %s)" % (", ".join(a.object or []) or a.maps, a.png, used, a.hdri))
        return 0
    finally:
        for ob, i, old in reversed(swapped):
            if i is None:
                ob.data.materials.pop()
            else:
                ob.material_slots[i].material = old
        for ob in made:
            me = ob.data
            bpy.data.objects.remove(ob)
            bpy.data.meshes.remove(me)
        if mat is not None:
            bpy.data.materials.remove(mat)


if __name__ == "__main__" and not globals().get("LOOKDEV_NO_MAIN"):
    sys.exit(main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []))
