"""Off-screen review renders for topology work: close-up wire, studio and reflective matcap, and contact sheets.

Host: Blender (bpy, gpu, numpy; tested on 5.2.2), live or headless.
Load in Blender:  ns = {}; exec(open(r"<skill>/scripts/review_render.py", encoding="utf-8").read(), ns)

    ns["render"](r"C:/.../corner-matcap.png", eye=(0, 2, -3), target=(0, 5, -1), light="MATCAP",
                 matcap="check_reflection_horizontal.exr", wire=True)
    with ns["isolate"](["MyPiece"], hide=["OldPiece"]): ns["render"](...)     # temporary visibility, restored after
    ns["contact_sheet"]([a.png, b.png, c.png, d.png], r"C:/.../sheet.png", cols=2)

Pass absolute output paths. Live, it works while Blender's window is minimised (it draws through
gpu.types.GPUOffScreen, not a screenshot) using a 3D viewport in the current screen, switched to Solid shading with
the requested light for the render; its shading and overlay settings are restored afterwards.
Headless (blender -b --factory-startup file.blend --python-exit-code 1 --python your_script.py), where there is no
viewport, it falls back to a Workbench scene render: the same camera, light and matcap, with wire drawn by temporary
Wireframe-modifier copies that keep every modifier except subdivision. Objects inside collection instances render but
get no wire there: review a piece in its KIT file. Matcap names are Blender's (check_reflection_horizontal.exr ships
with 5.2.2).
A matcap shows curved bands across flat faces in a perspective view: that is the matcap, not smooth shading.
"""

import contextlib

import bpy
import gpu
import numpy as np
from mathutils import Vector


def _view3d():
    area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
    return area, next(r for r in area.regions if r.type == 'WINDOW'), area.spaces.active


def render(path, eye, target, matrix=None, lens=24, w=1200, h=800, light="STUDIO", matcap=None, wire=False):
    """Render from eye towards target (object-space points, transformed by matrix if given, for example a placed
    object's matrix_world) to a PNG. light: 'STUDIO', 'MATCAP' (matcap: a studio-light name such as
    'check_reflection_horizontal.exr') or 'FLAT'."""
    eye, target = Vector(eye), Vector(target)
    if matrix is not None:
        eye, target = matrix @ eye, matrix @ target
    cd = bpy.data.cameras.new("_review_cam")
    cd.lens, cd.clip_start, cd.clip_end = lens, 0.02, 1000.0
    cam = bpy.data.objects.new("_review_cam", cd)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = eye
    cam.rotation_euler = (target - eye).to_track_quat('-Z', 'Y').to_euler()
    bpy.context.view_layer.update()
    if bpy.app.background or bpy.context.screen is None or not any(
            a.type == 'VIEW_3D' for a in bpy.context.screen.areas):
        try:
            return _render_scene(path, cam, w, h, light, matcap, wire, (target - eye).length)
        finally:
            bpy.data.objects.remove(cam)
            bpy.data.cameras.remove(cd)
    area, region, sp = _view3d()
    sh, ov = sp.shading, sp.overlay
    keep_type = sh.type
    keep = (sh.light, sh.studio_light, ov.show_overlays, ov.show_wireframes, ov.wireframe_threshold, ov.show_floor,
            ov.show_axis_x, ov.show_axis_y, ov.show_cursor, ov.show_object_origins)
    try:
        sh.type = 'SOLID'                     # the light settings below apply to Solid shading only
        sh.light = light
        if matcap:
            sh.studio_light = matcap
        ov.show_overlays = True
        ov.show_wireframes, ov.wireframe_threshold = wire, 1.0
        ov.show_floor = ov.show_axis_x = ov.show_axis_y = ov.show_cursor = ov.show_object_origins = False
        view = cam.matrix_world.inverted()
        proj = cam.calc_matrix_camera(bpy.context.evaluated_depsgraph_get(), x=w, y=h)
        off = gpu.types.GPUOffScreen(w, h)
        try:
            off.draw_view3d(bpy.context.scene, bpy.context.view_layer, sp, region, view, proj,
                            do_color_management=True)
            buf = off.texture_color.read()
            buf.dimensions = w * h * 4
            px = np.asarray(buf, dtype=np.float32) / 255.0
        finally:
            off.free()
        _save(px, w, h, path)
    finally:
        (sh.light, sh.studio_light, ov.show_overlays, ov.show_wireframes, ov.wireframe_threshold, ov.show_floor,
         ov.show_axis_x, ov.show_axis_y, ov.show_cursor, ov.show_object_origins) = keep
        sh.type = keep_type
        bpy.data.objects.remove(cam)
        bpy.data.cameras.remove(cd)
    return path


def _render_scene(path, cam, w, h, light, matcap, wire, distance):
    """Headless path (blender -b has no 3D viewport or GPU context for GPUOffScreen): a Workbench scene render.
    Wireframe overlays do not exist in a render, so wire=True adds temporary copies of the visible meshes with a
    Wireframe modifier after their own modifiers (subdivision dropped, so the wire is the cage the viewport shows),
    drawn dark, and removes them afterwards. Nothing is saved."""
    scene = bpy.context.scene
    sh = scene.display.shading
    keep_scene = (scene.camera, scene.render.engine, scene.render.resolution_x, scene.render.resolution_y,
                  scene.render.resolution_percentage, scene.render.filepath, scene.render.image_settings.file_format)
    keep_sh = (sh.light, sh.studio_light, sh.color_type, sh.single_color[:])
    shown = [o for o in scene.objects if o.type == 'MESH' and o.visible_get()]
    # A render ignores viewport hide flags (isolate() sets those), so hide the hidden ones from the render as well.
    unrender = [o for o in scene.objects if o.type == 'MESH' and not o.visible_get() and not o.hide_render]
    copies = []
    try:
        for o in unrender:
            o.hide_render = True
        scene.camera = cam
        scene.render.engine = 'BLENDER_WORKBENCH'
        scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = w, h, 100
        scene.render.image_settings.file_format = 'PNG'
        scene.render.filepath = path
        sh.light = light
        if matcap:
            sh.studio_light = matcap
        if wire:
            sh.color_type = 'OBJECT'           # originals light grey, wire copies near black
            thickness = max(0.0015, distance * 0.0012)
            for ob in shown:
                dup = ob.copy()                 # shares the mesh data; only the copy gets the modifier
                for m in [m for m in dup.modifiers if m.type in {'SUBSURF', 'MULTIRES'}]:
                    dup.modifiers.remove(m)     # keep mirror, array, bevel...: the wire must match the surface
                mod = dup.modifiers.new("_review_wire", 'WIREFRAME')
                mod.thickness, mod.use_even_offset, mod.use_replace = thickness, True, True
                dup.color = (0.02, 0.02, 0.02, 1.0)
                scene.collection.objects.link(dup)
                copies.append((dup, ob, ob.color[:]))
                ob.color = (0.8, 0.8, 0.8, 1.0)
        bpy.ops.render.render(write_still=True)
    finally:
        for o in unrender:
            o.hide_render = False
        for dup, ob, colour in copies:
            ob.color = colour
            bpy.data.objects.remove(dup)
        (scene.camera, scene.render.engine, scene.render.resolution_x, scene.render.resolution_y,
         scene.render.resolution_percentage, scene.render.filepath,
         scene.render.image_settings.file_format) = keep_scene
        sh.light, sh.studio_light, sh.color_type, sh.single_color = keep_sh
    return path


def _save(px, w, h, path):
    img = bpy.data.images.new("_review_img", w, h, alpha=True)
    try:
        img.pixels.foreach_set(np.asarray(px, dtype=np.float32).ravel())
        img.filepath_raw = path
        img.file_format = 'PNG'
        img.save()
    finally:
        bpy.data.images.remove(img)


@contextlib.contextmanager
def isolate(show, hide=()):
    """Temporarily show the named objects and hide others named in `hide` (view-layer hide flags), restoring them on
    exit. Objects in excluded collections cannot be shown this way: link previews into a visible collection of your own
    rather than un-excluding the user's."""
    names = list(show) + list(hide)
    was = {n: bpy.data.objects[n].hide_get() for n in names}
    try:
        for n in show:
            bpy.data.objects[n].hide_set(False)
        for n in hide:
            bpy.data.objects[n].hide_set(True)
        bpy.context.view_layer.update()
        yield
    finally:
        for n, h in was.items():
            bpy.data.objects[n].hide_set(h)
        bpy.context.view_layer.update()


def contact_sheet(paths, out, cols=2):
    """Tile equally sized PNGs into one image, left to right, top to bottom."""
    ims = []
    for p in paths:
        im = bpy.data.images.load(p)
        try:
            ims.append(np.array(im.pixels[:], dtype=np.float32).reshape(im.size[1], im.size[0], 4))
        finally:
            bpy.data.images.remove(im)
    h, w = ims[0].shape[:2]
    rows = [ims[i:i + cols] + [np.zeros_like(ims[0])] * (cols - len(ims[i:i + cols])) for i in range(0, len(ims), cols)]
    grid = np.vstack([np.hstack(r) for r in rows][::-1])        # Blender images are stored bottom row first
    _save(grid, grid.shape[1], grid.shape[0], out)
    return out
