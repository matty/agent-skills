"""Off-screen review renders for topology work: close-up wire, studio and reflective matcap, and contact sheets.

Load in Blender:  ns = {}; exec(open(r"<skill>/scripts/review_render.py", encoding="utf-8").read(), ns)

    ns["render"](r"C:/.../corner-matcap.png", eye=(0, 2, -3), target=(0, 5, -1), light="MATCAP",
                 matcap="check_reflection_horizontal.exr", wire=True)
    with ns["isolate"](["MyPiece"], hide=["OldPiece"]): ns["render"](...)     # temporary visibility, restored after
    ns["contact_sheet"]([a.png, b.png, c.png, d.png], r"C:/.../sheet.png", cols=2)

Works while Blender's window is minimised (it draws through gpu.types.GPUOffScreen, not a screenshot). Needs a 3D
viewport in the current screen; its shading/overlay settings are changed only for the render and restored.
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
    area, region, sp = _view3d()
    sh, ov = sp.shading, sp.overlay
    keep = (sh.light, sh.studio_light, ov.show_overlays, ov.show_wireframes, ov.wireframe_threshold, ov.show_floor,
            ov.show_axis_x, ov.show_axis_y, ov.show_cursor, ov.show_object_origins)
    try:
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
        bpy.data.objects.remove(cam)
        bpy.data.cameras.remove(cd)
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
